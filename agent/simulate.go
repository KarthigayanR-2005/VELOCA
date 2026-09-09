package main

import (
	"hash/fnv"
	"math"
	"math/rand"
	"strconv"
	"sync"
	"time"
)

const (
	maxQueue          = 200.0 // queue_depth clamp
	queueUpK          = 0.6   // how fast the queue builds per Mbps of overload, per tick
	queueDrainK       = 0.35  // fraction of backlog drained per tick once under capacity
	latencyQFactor    = 2.0   // ms added per unit of queue depth
	maxLatencyMs      = 2000.0
	utilCapForFormula = 0.97 // util fed into the M/M/1 term is capped just under 1 so it stays finite
	spilloverFraction = 0.20 // fraction of a node's served load forwarded on to each neighbor as cross-traffic

	loadStaleAfter = 8 * time.Second // external load override reverts to baseline if not refreshed
	flowStaleAfter = 5 * time.Second // inbound neighbor flow is dropped from the sum if not refreshed
)

// simulator holds one node's persistent physical state (its queue) across
// ticks, plus the fixed facts about it (baseline, capacity, RNG).
type simulator struct {
	baseline     Baseline
	capacityMbps float64
	rng          *rand.Rand
	queueDepth   float64 // internal, unjittered — the real backlog
}

// tick advances the queueing model by one second given the total load
// currently offered to this node (external + inbound from neighbors), and
// returns the metrics to publish.
func (s *simulator) tick(nodeID string, offeredTotal float64, chaos *chaosState) Metrics {
	served := math.Min(offeredTotal, s.capacityMbps)
	excess := offeredTotal - served // > 0 only while overloaded

	if excess > 0 {
		s.queueDepth += excess * queueUpK
	} else {
		s.queueDepth -= s.queueDepth * queueDrainK
	}
	s.queueDepth = clamp(s.queueDepth, 0, maxQueue)

	util := 0.0
	if s.capacityMbps > 0 {
		util = offeredTotal / s.capacityMbps
	}
	utilForFormula := math.Min(util, utilCapForFormula)
	// M/M/1-style term: latency rises sharply as utilisation approaches 1.
	mm1Term := s.baseline.LatencyMs * utilForFormula / (1 - utilForFormula)

	injectedLatency := chaos.currentLatencyMs()
	latency := s.baseline.LatencyMs + mm1Term + s.queueDepth*latencyQFactor + injectedLatency
	latency = clamp(latency, 0, maxLatencyMs)

	overflowLossPct := 0.0
	if offeredTotal > s.capacityMbps && offeredTotal > 0 {
		// how much demand capacity alone could never serve...
		overflowRatio := (offeredTotal - s.capacityMbps) / offeredTotal
		// ...tempered by how full the queue actually is: a fresh burst
		// drains into the queue first and only starts costing packets
		// once that backlog is close to full.
		queueSaturation := s.queueDepth / maxQueue
		overflowLossPct = overflowRatio * queueSaturation * 100
	}
	injectedLossPct := chaos.maxActiveLossPct()
	packetLoss := clamp(s.baseline.PacketLossPct+overflowLossPct+injectedLossPct, 0, 100)

	// small gaussian jitter on the reported values only, so nothing is
	// perfectly deterministic but the underlying queue state stays clean.
	return Metrics{
		NodeID:          nodeID,
		Timestamp:       time.Now().Unix(),
		OfferedLoadMbps: offeredTotal,
		ThroughputMbps:  jitter(s.rng, served, 0.03),
		LatencyMs:       jitter(s.rng, latency, 0.05),
		QueueDepth:      jitter(s.rng, s.queueDepth, 0.05),
		PacketLossPct:   jitter(s.rng, packetLoss, 0.05),
	}
}

func clamp(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func jitter(rng *rand.Rand, v, stddevFrac float64) float64 {
	out := v + rng.NormFloat64()*v*stddevFrac
	if out < 0 {
		return 0
	}
	return out
}

// newSeededRNG derives a per-node RNG from a global SEED env var plus the
// node's own ID, so the same SEED always reproduces the same per-node
// noise (needed to compare two runs of the same scenario) while still
// giving every node a different noise sequence.
func newSeededRNG(seedStr, nodeID string) *rand.Rand {
	base, err := strconv.ParseInt(seedStr, 10, 64)
	if err != nil {
		base = 1
	}
	h := fnv.New64a()
	_, _ = h.Write([]byte(nodeID))
	return rand.New(rand.NewSource(base ^ int64(h.Sum64())))
}

// externalLoad is the offered_load_mbps an operator (loadgen) has set for
// this node via veloca.load.<node_id>. It reverts to the topology baseline
// on its own if no update arrives for a while, so a crashed loadgen or a
// forgotten override can't strand a node at an artificial load forever.
type externalLoad struct {
	mu        sync.Mutex
	value     float64
	hasValue  bool
	updatedAt time.Time
}

func (s *externalLoad) set(v float64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.value = v
	s.hasValue = true
	s.updatedAt = time.Now()
}

func (s *externalLoad) get(fallback float64) float64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.hasValue {
		return fallback
	}
	if time.Since(s.updatedAt) > loadStaleAfter {
		s.hasValue = false
		return fallback
	}
	return s.value
}

// inboundFlows is the latest reported delivery from each neighbor over
// veloca.flow.<node_id>, used to fold neighbors' cross-traffic into this
// node's own offered load. Entries expire if a neighbor stops publishing.
type inboundFlows struct {
	mu    sync.Mutex
	value map[string]float64
	seen  map[string]time.Time
}

func newInboundFlows() *inboundFlows {
	return &inboundFlows{value: make(map[string]float64), seen: make(map[string]time.Time)}
}

func (f *inboundFlows) record(from string, mbps float64) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.value[from] = mbps
	f.seen[from] = time.Now()
}

func (f *inboundFlows) sum() float64 {
	f.mu.Lock()
	defer f.mu.Unlock()
	total := 0.0
	now := time.Now()
	for from, v := range f.value {
		if now.Sub(f.seen[from]) > flowStaleAfter {
			continue
		}
		total += v
	}
	return total
}
