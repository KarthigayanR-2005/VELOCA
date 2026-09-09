// Command agent simulates one network node. It reads its identity from
// NODE_ID, registers itself with the control-plane over NATS, then runs a
// small queueing simulation every tick: it takes whatever load is offered
// to it (externally set, plus whatever neighbors forward to it), serves as
// much as its capacity allows, and reports the resulting throughput,
// latency, queue depth and packet loss — both over NATS and via a
// Prometheus /metrics endpoint. It also reacts to load and chaos commands
// published by loadgen/ and chaos/.
package main

import (
	"encoding/json"
	"log"
	"os"
	"time"

	"github.com/nats-io/nats.go"
)

func main() {
	nodeID := os.Getenv("NODE_ID")
	if nodeID == "" {
		log.Fatal("NODE_ID env var is required")
	}
	natsURL := getenv("NATS_URL", nats.DefaultURL)
	topologyPath := getenv("TOPOLOGY_PATH", "/app/topology.yaml")
	metricsAddr := getenv("METRICS_ADDR", ":9100")
	seedStr := getenv("SEED", "1")

	topo := loadTopologyFile(topologyPath)
	baseline := findBaseline(topo, nodeID)
	neighbors, capacityMbps := neighborsOf(topo, nodeID)
	log.Printf("node %s: capacity=%.0fMbps (bottleneck link), %d neighbors", nodeID, capacityMbps, len(neighbors))

	nc, err := nats.Connect(natsURL, nats.Timeout(5*time.Second), nats.RetryOnFailedConnect(true), nats.MaxReconnects(-1))
	if err != nil {
		log.Fatalf("connecting to NATS at %s: %v", natsURL, err)
	}
	defer nc.Close()

	if err := nc.Publish("veloca.register", []byte(nodeID)); err != nil {
		log.Printf("register publish failed: %v", err)
	}
	log.Printf("agent %s registered, publishing metrics to veloca.metrics.%s", nodeID, nodeID)

	gauges := newGaugeSet(nodeID)
	go serveMetrics(metricsAddr)

	load := &externalLoad{}
	inbound := newInboundFlows()
	chaos := newChaosState()

	if _, err := nc.Subscribe("veloca.load."+nodeID, func(msg *nats.Msg) {
		var m loadMsg
		if err := json.Unmarshal(msg.Data, &m); err != nil {
			log.Printf("bad load payload: %v", err)
			return
		}
		load.set(m.OfferedLoadMbps)
		log.Printf("load override: offered_load_mbps=%.1f", m.OfferedLoadMbps)
	}); err != nil {
		log.Fatalf("subscribing to veloca.load.%s: %v", nodeID, err)
	}

	if _, err := nc.Subscribe("veloca.flow."+nodeID, func(msg *nats.Msg) {
		var f flowMsg
		if err := json.Unmarshal(msg.Data, &f); err != nil {
			return
		}
		inbound.record(f.From, f.Mbps)
	}); err != nil {
		log.Fatalf("subscribing to veloca.flow.%s: %v", nodeID, err)
	}

	if _, err := nc.Subscribe("veloca.chaos."+nodeID, func(msg *nats.Msg) {
		handleChaos(msg.Data, nodeID, neighbors, chaos)
	}); err != nil {
		log.Fatalf("subscribing to veloca.chaos.%s: %v", nodeID, err)
	}

	// Phase 4 will act on these; for now just observe them.
	if _, err := nc.Subscribe("veloca.action."+nodeID, func(msg *nats.Msg) {
		log.Printf("action received (not yet acted on): %s", string(msg.Data))
	}); err != nil {
		log.Fatalf("subscribing to veloca.action.%s: %v", nodeID, err)
	}

	sim := &simulator{
		baseline:     baseline,
		capacityMbps: capacityMbps,
		rng:          newSeededRNG(seedStr, nodeID),
	}

	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()
	for range ticker.C {
		offeredTotal := load.get(baseline.ThroughputMbps) + inbound.sum()

		m := sim.tick(nodeID, offeredTotal, chaos)
		gauges.set(m)
		publishMetrics(nc, nodeID, m)
		_ = nc.Publish("veloca.register", []byte(nodeID))

		forwardEach := m.ThroughputMbps * spilloverFraction / float64(len(neighbors))
		for _, nb := range neighbors {
			lossPct := chaos.currentLossPct(nb.PeerID)
			delivered := forwardEach * (1 - lossPct/100)
			publishFlow(nc, nb.PeerID, nodeID, delivered)
		}
	}
}

// handleChaos applies one chaos command to this agent's state. "kill"
// exits the process outright (simulating a node going down and simply
// stopping publishing); "latency" and "loss" register a timed effect.
func handleChaos(data []byte, nodeID string, neighbors []neighbor, chaos *chaosState) {
	var c chaosMsg
	if err := json.Unmarshal(data, &c); err != nil {
		log.Printf("bad chaos payload: %v", err)
		return
	}
	switch c.Type {
	case "kill":
		log.Printf("chaos: kill received — exiting")
		os.Exit(0)
	case "latency":
		d := time.Duration(c.DurationS * float64(time.Second))
		chaos.applyLatency(c.ExtraLatencyMs, d)
		log.Printf("chaos: +%.0fms latency for %s", c.ExtraLatencyMs, d)
	case "loss":
		peer, ok := neighborForLink(neighbors, nodeID, c.Target)
		if !ok {
			log.Printf("chaos: loss target %q is not one of my links, ignoring", c.Target)
			return
		}
		d := time.Duration(c.DurationS * float64(time.Second))
		chaos.applyLoss(peer, c.LossPct, d)
		log.Printf("chaos: +%.0f%% loss to %s for %s", c.LossPct, peer, d)
	default:
		log.Printf("chaos: unknown type %q, ignoring", c.Type)
	}
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
