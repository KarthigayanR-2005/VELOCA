package main

import (
	"bytes"
	"encoding/json"
	"log"
	"net/http"
	"time"
)

// postAnnotation drops a marker on the Grafana timeline for an executed
// action. Mirrors loadgen/annotate.go, chaos/annotate.go, and
// causal-engine's annotate.py — every event source posts its own.
func postAnnotation(baseURL, user, pass, text string, tags []string, at time.Time) {
	body, err := json.Marshal(map[string]any{
		"time": at.UnixMilli(),
		"tags": tags,
		"text": text,
	})
	if err != nil {
		return
	}
	req, err := http.NewRequest(http.MethodPost, baseURL+"/api/annotations", bytes.NewReader(body))
	if err != nil {
		log.Printf("annotation request: %v", err)
		return
	}
	req.SetBasicAuth(user, pass)
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("annotation post failed (is Grafana reachable at %s?): %v", baseURL, err)
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		log.Printf("annotation post returned %s", resp.Status)
	}
}
