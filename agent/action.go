package main

import (
	"encoding/json"
	"log"
	"sync"
	"time"
)

// actionMsg is published by control-plane on veloca.action.<node_id> when
// an approved verdict is executed. Only "cap_offered_load" is implemented
// (Phase 4's proposed action); anything else is logged and ignored.
type actionMsg struct {
	ActionID  string  `json:"action_id"`
	Type      string  `json:"type"`
	CapMbps   float64 `json:"cap_mbps"`
	DurationS float64 `json:"duration_s"`
}

// actionCap tracks a currently-active "cap offered_load" action. While
// active, whatever the load generator (or baseline) says gets clamped
// down to capMbps; once it expires, control reverts to the load
// generator/baseline with no lingering effect.
type actionCap struct {
	mu        sync.Mutex
	active    bool
	capMbps   float64
	expiresAt time.Time
}

func (a *actionCap) apply(rawExternal float64) float64 {
	a.mu.Lock()
	defer a.mu.Unlock()
	if !a.active {
		return rawExternal
	}
	if time.Now().After(a.expiresAt) {
		a.active = false
		return rawExternal
	}
	if rawExternal > a.capMbps {
		return a.capMbps
	}
	return rawExternal
}

func (a *actionCap) set(capMbps float64, duration time.Duration) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.active = true
	a.capMbps = capMbps
	a.expiresAt = time.Now().Add(duration)
}

// handleAction applies an action command. Every applied cap is logged
// with its before/after offered load so the effect is visible in
// `docker compose logs agent-<node>` even without cross-referencing
// experiments/logs/actions.jsonl (the control-plane's authoritative record).
func handleAction(data []byte, nodeID string, cap *actionCap, load *externalLoad, baseline Baseline) {
	var a actionMsg
	if err := json.Unmarshal(data, &a); err != nil {
		log.Printf("bad action payload: %v", err)
		return
	}
	if a.Type != "cap_offered_load" {
		log.Printf("action: unknown type %q, ignoring", a.Type)
		return
	}
	before := load.get(baseline.ThroughputMbps)
	d := time.Duration(a.DurationS * float64(time.Second))
	cap.set(a.CapMbps, d)
	after := cap.apply(before)
	log.Printf("action %s applied: cap_offered_load=%.1fMbps for %s | offered_load before=%.1f after=%.1f at %s",
		a.ActionID, a.CapMbps, d, before, after, time.Now().UTC().Format(time.RFC3339))
}
