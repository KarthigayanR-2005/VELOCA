package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

// groundTruthRecord is one line of experiments/logs/ground_truth.jsonl —
// the answer key later evaluation compares detections against. Ts is the
// real fire time (after any --at delay has elapsed), not process start.
type groundTruthRecord struct {
	Ts        string         `json:"ts"`
	Type      string         `json:"type"`
	Target    string         `json:"target"`
	Params    map[string]any `json:"params"`
	DurationS float64        `json:"duration_s"`
}

func appendGroundTruth(dir string, rec groundTruthRecord) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	path := filepath.Join(dir, "ground_truth.jsonl")
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	defer f.Close()

	line, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	_, err = f.Write(append(line, '\n'))
	return err
}

func rfc3339(t time.Time) string {
	return t.UTC().Format(time.RFC3339)
}
