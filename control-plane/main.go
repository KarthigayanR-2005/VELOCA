// Command control-plane loads the network topology, tracks each node's
// liveness and latest metrics as agents report in over NATS, and exposes
// that state over HTTP. It issues no commands yet (that's Phase 4).
package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"sync"
	"time"

	"github.com/nats-io/nats.go"
)

const aliveWindow = 3 * time.Second

// Metrics mirrors the JSON an agent publishes on veloca.metrics.<node_id>.
type Metrics struct {
	NodeID          string  `json:"node_id"`
	Timestamp       int64   `json:"timestamp"`
	OfferedLoadMbps float64 `json:"offered_load_mbps"`
	ThroughputMbps  float64 `json:"throughput_mbps"`
	LatencyMs       float64 `json:"latency_ms"`
	QueueDepth      float64 `json:"queue_depth"`
	PacketLossPct   float64 `json:"packet_loss_pct"`
}

// NodeState is what GET /nodes reports for a single node.
type NodeState struct {
	ID       string     `json:"id"`
	Alive    bool       `json:"alive"`
	LastSeen *time.Time `json:"last_seen,omitempty"`
	Metrics  *Metrics   `json:"metrics,omitempty"`
}

// registry is the control-plane's in-memory view of the network, built
// entirely from what agents report over NATS.
type registry struct {
	mu       sync.Mutex
	lastSeen map[string]time.Time
	metrics  map[string]Metrics
}

func newRegistry() *registry {
	return &registry{
		lastSeen: make(map[string]time.Time),
		metrics:  make(map[string]Metrics),
	}
}

func (r *registry) markSeen(nodeID string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.lastSeen[nodeID] = time.Now()
}

func (r *registry) recordMetrics(m Metrics) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.metrics[m.NodeID] = m
	r.lastSeen[m.NodeID] = time.Now()
}

func (r *registry) snapshot(nodeIDs []string) []NodeState {
	r.mu.Lock()
	defer r.mu.Unlock()

	states := make([]NodeState, 0, len(nodeIDs))
	for _, id := range nodeIDs {
		s := NodeState{ID: id}
		if seen, ok := r.lastSeen[id]; ok {
			t := seen
			s.LastSeen = &t
			s.Alive = time.Since(seen) < aliveWindow
		}
		if m, ok := r.metrics[id]; ok {
			mCopy := m
			s.Metrics = &mCopy
		}
		states = append(states, s)
	}
	return states
}

func main() {
	natsURL := getenv("NATS_URL", nats.DefaultURL)
	topologyPath := getenv("TOPOLOGY_PATH", "/app/topology.yaml")
	httpAddr := getenv("HTTP_ADDR", ":8080")
	actionsLogPath := getenv("ACTIONS_LOG_PATH", "/app/logs/actions.jsonl")
	grafanaURL := getenv("GRAFANA_URL", "")
	grafanaUser := getenv("GRAFANA_USER", "admin")
	grafanaPass := getenv("GRAFANA_PASS", "admin")

	topo, err := loadTopology(topologyPath)
	if err != nil {
		log.Fatalf("loading topology %s: %v", topologyPath, err)
	}
	nodeIDs := topo.NodeIDs()
	log.Printf("loaded topology: %d nodes, %d links", len(topo.Nodes), len(topo.Links))

	reg := newRegistry()

	nc, err := nats.Connect(natsURL, nats.Timeout(5*time.Second), nats.RetryOnFailedConnect(true), nats.MaxReconnects(-1))
	if err != nil {
		log.Fatalf("connecting to NATS at %s: %v", natsURL, err)
	}
	defer nc.Close()

	if _, err := nc.Subscribe("veloca.register", func(msg *nats.Msg) {
		reg.markSeen(string(msg.Data))
	}); err != nil {
		log.Fatalf("subscribing to veloca.register: %v", err)
	}

	if _, err := nc.Subscribe("veloca.metrics.*", func(msg *nats.Msg) {
		var m Metrics
		if err := json.Unmarshal(msg.Data, &m); err != nil {
			log.Printf("bad metrics payload on %s: %v", msg.Subject, err)
			return
		}
		reg.recordMetrics(m)
	}); err != nil {
		log.Fatalf("subscribing to veloca.metrics.*: %v", err)
	}

	alog := newActionLog(actionsLogPath)

	mux := http.NewServeMux()
	mux.HandleFunc("/nodes", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(reg.snapshot(nodeIDs))
	})
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	mux.HandleFunc("/execute", executeHandler(nc, alog, grafanaURL, grafanaUser, grafanaPass))
	mux.HandleFunc("/actions", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(alog.recentRecords())
	})

	log.Printf("control-plane listening on %s", httpAddr)
	if err := http.ListenAndServe(httpAddr, mux); err != nil {
		log.Fatalf("http server: %v", err)
	}
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
