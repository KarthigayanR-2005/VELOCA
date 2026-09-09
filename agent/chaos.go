package main

import (
	"sync"
	"time"
)

// chaosState tracks this agent's currently-active injected faults. NATS
// callbacks write to it from their own goroutines while the tick loop
// reads it, so every access goes through the mutex.
type chaosState struct {
	mu sync.Mutex

	extraLatencyMs   float64
	latencyExpiresAt time.Time

	// extra packet loss applied when forwarding to a specific neighbor,
	// keyed by neighbor node ID (one active loss fault per neighbor link).
	lossPct    map[string]float64
	lossExpiry map[string]time.Time
}

func newChaosState() *chaosState {
	return &chaosState{
		lossPct:    make(map[string]float64),
		lossExpiry: make(map[string]time.Time),
	}
}

func (c *chaosState) applyLatency(extraMs float64, duration time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.extraLatencyMs = extraMs
	c.latencyExpiresAt = time.Now().Add(duration)
}

func (c *chaosState) applyLoss(neighborID string, pct float64, duration time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.lossPct[neighborID] = pct
	c.lossExpiry[neighborID] = time.Now().Add(duration)
}

// currentLatencyMs returns the active injected latency, clearing it once
// its window has passed.
func (c *chaosState) currentLatencyMs() float64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.extraLatencyMs > 0 && time.Now().After(c.latencyExpiresAt) {
		c.extraLatencyMs = 0
	}
	return c.extraLatencyMs
}

// currentLossPct returns the active injected loss percentage for traffic
// forwarded to neighborID, clearing it once its window has passed.
func (c *chaosState) currentLossPct(neighborID string) float64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	pct, ok := c.lossPct[neighborID]
	if !ok {
		return 0
	}
	if time.Now().After(c.lossExpiry[neighborID]) {
		delete(c.lossPct, neighborID)
		delete(c.lossExpiry, neighborID)
		return 0
	}
	return pct
}

// maxActiveLossPct is used to bump this node's own reported
// packet_loss_pct while any outgoing link of ours is dropping packets.
func (c *chaosState) maxActiveLossPct() float64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now()
	max := 0.0
	for id, exp := range c.lossExpiry {
		if now.After(exp) {
			continue
		}
		if p := c.lossPct[id]; p > max {
			max = p
		}
	}
	return max
}
