// Executes approved causal-engine verdicts: publishes an action to the
// target agent, records it (in-memory + experiments/logs/actions.jsonl),
// and returns the action_id. Rejects (does nothing to agents) if the
// verdict isn't approved — this is enforced here too, not just trusted
// from the caller, since a bad or replayed request should never be able
// to act on a live agent just by omitting the check upstream.
package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
)

// ProposedAction mirrors causal-engine's verdict["proposed_action"].
type ProposedAction struct {
	Type       string  `json:"type"`
	Node       string  `json:"node"`
	TargetNode string  `json:"target_node"`
	CapMbps    float64 `json:"cap_mbps"`
	DurationS  float64 `json:"duration_s"`
}

// RootCause mirrors one entry of causal-engine's verdict["root_causes"].
type RootCause struct {
	Node  string  `json:"node"`
	Score float64 `json:"score"`
}

// Verdict is the subset of causal-engine's /diagnose response /execute
// needs — extra fields in the real payload are simply ignored by
// json.Unmarshal.
type Verdict struct {
	ID             string          `json:"id"`
	Approved       bool            `json:"approved"`
	ProposedAction *ProposedAction `json:"proposed_action"`
	RootCauses     []RootCause     `json:"root_causes"`
}

// ExecuteResponse is always HTTP 200 for a well-formed request — callers
// check the Executed field for the business-logic outcome, not the status
// code, so an orchestrator can tell "declined" apart from "network error".
type ExecuteResponse struct {
	Executed bool   `json:"executed"`
	ActionID string `json:"action_id,omitempty"`
	Reason   string `json:"reason"`
}

// ActionRecord is one line of experiments/logs/actions.jsonl.
type ActionRecord struct {
	Event      string      `json:"event"` // "executed"
	ActionID   string      `json:"action_id"`
	VerdictID  string      `json:"verdict_id"`
	Node       string      `json:"node"`
	CapMbps    float64     `json:"cap_mbps"`
	DurationS  float64     `json:"duration_s"`
	RootCauses []RootCause `json:"root_causes"`
	ExecutedAt string      `json:"executed_at"`
}

type actionLog struct {
	mu   sync.Mutex
	path string

	recordsMu sync.Mutex
	recent    []ActionRecord
}

func newActionLog(path string) *actionLog {
	return &actionLog{path: path}
}

func (l *actionLog) append(rec ActionRecord) error {
	l.mu.Lock()
	defer l.mu.Unlock()

	if err := os.MkdirAll(filepath.Dir(l.path), 0o755); err != nil {
		return err
	}
	f, err := os.OpenFile(l.path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	defer f.Close()

	line, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	if _, err := f.Write(append(line, '\n')); err != nil {
		return err
	}

	l.recordsMu.Lock()
	l.recent = append(l.recent, rec)
	if len(l.recent) > 50 {
		l.recent = l.recent[len(l.recent)-50:]
	}
	l.recordsMu.Unlock()
	return nil
}

func (l *actionLog) recentRecords() []ActionRecord {
	l.recordsMu.Lock()
	defer l.recordsMu.Unlock()
	out := make([]ActionRecord, len(l.recent))
	copy(out, l.recent)
	return out
}

// executeHandler builds the POST /execute HTTP handler. nc publishes the
// action to the agent; log records it; grafanaURL/user/pass (empty
// grafanaURL disables) posts a marker for it.
func executeHandler(nc *nats.Conn, alog *actionLog, grafanaURL, grafanaUser, grafanaPass string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			json.NewEncoder(w).Encode(ExecuteResponse{Executed: false, Reason: "POST required"})
			return
		}

		var v Verdict
		if err := json.NewDecoder(r.Body).Decode(&v); err != nil {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(ExecuteResponse{Executed: false, Reason: fmt.Sprintf("bad verdict JSON: %v", err)})
			return
		}

		if !v.Approved {
			reason := "verdict not approved"
			log.Printf("execute: rejected verdict %s: %s", v.ID, reason)
			json.NewEncoder(w).Encode(ExecuteResponse{Executed: false, Reason: reason})
			return
		}
		if v.ProposedAction == nil {
			reason := "verdict approved but has no proposed_action"
			log.Printf("execute: rejected verdict %s: %s", v.ID, reason)
			json.NewEncoder(w).Encode(ExecuteResponse{Executed: false, Reason: reason})
			return
		}
		action := v.ProposedAction
		if action.Node == "" {
			reason := "proposed_action has no target node"
			log.Printf("execute: rejected verdict %s: %s", v.ID, reason)
			json.NewEncoder(w).Encode(ExecuteResponse{Executed: false, Reason: reason})
			return
		}

		actionID := uuid.NewString()
		payload, _ := json.Marshal(actionMsg{
			ActionID: actionID, Type: action.Type,
			CapMbps: action.CapMbps, DurationS: action.DurationS,
		})
		subject := "veloca.action." + action.Node
		if err := nc.Publish(subject, payload); err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(ExecuteResponse{Executed: false, Reason: fmt.Sprintf("publishing to %s: %v", subject, err)})
			return
		}
		nc.Flush()

		now := time.Now().UTC()
		rec := ActionRecord{
			Event: "executed", ActionID: actionID, VerdictID: v.ID,
			Node: action.Node, CapMbps: action.CapMbps, DurationS: action.DurationS,
			RootCauses: v.RootCauses, ExecutedAt: now.Format(time.RFC3339),
		}
		if err := alog.append(rec); err != nil {
			log.Printf("execute: writing actions.jsonl: %v", err)
		}

		log.Printf("execute: action %s applied to %s (cap=%.1fMbps for %.0fs), verdict=%s", actionID, action.Node, action.CapMbps, action.DurationS, v.ID)

		if grafanaURL != "" {
			text := fmt.Sprintf("action %s: cap %s to %.0fMbps for %.0fs", actionID[:8], action.Node, action.CapMbps, action.DurationS)
			go postAnnotation(grafanaURL, grafanaUser, grafanaPass, text, []string{"veloca", "action"}, now)
		}

		json.NewEncoder(w).Encode(ExecuteResponse{Executed: true, ActionID: actionID, Reason: "applied"})
	}
}

// actionMsg mirrors agent/action.go's wire format exactly.
type actionMsg struct {
	ActionID  string  `json:"action_id"`
	Type      string  `json:"type"`
	CapMbps   float64 `json:"cap_mbps"`
	DurationS float64 `json:"duration_s"`
}
