package main

import (
	"encoding/json"
	"log"
	"net/http"

	"github.com/nats-io/nats.go"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// Metrics is published on veloca.metrics.<node_id> and mirrored to
// Prometheus. ThroughputMbps is what the node actually delivered (after
// its capacity clamp); OfferedLoadMbps is the demand it was facing.
type Metrics struct {
	NodeID          string  `json:"node_id"`
	Timestamp       int64   `json:"timestamp"`
	OfferedLoadMbps float64 `json:"offered_load_mbps"`
	ThroughputMbps  float64 `json:"throughput_mbps"`
	LatencyMs       float64 `json:"latency_ms"`
	QueueDepth      float64 `json:"queue_depth"`
	PacketLossPct   float64 `json:"packet_loss_pct"`
}

// loadMsg is published by loadgen on veloca.load.<node_id> to override a
// node's external offered load.
type loadMsg struct {
	OfferedLoadMbps float64 `json:"offered_load_mbps"`
}

// flowMsg is what a node publishes on veloca.flow.<to_node_id> to tell a
// neighbor how much traffic it just forwarded to it.
type flowMsg struct {
	From string  `json:"from"`
	Mbps float64 `json:"mbps"`
}

// chaosMsg is published by the chaos CLI on veloca.chaos.<node_id>.
type chaosMsg struct {
	Type           string  `json:"type"` // "kill" | "latency" | "loss"
	Target         string  `json:"target"`
	ExtraLatencyMs float64 `json:"extra_latency_ms,omitempty"`
	LossPct        float64 `json:"loss_pct,omitempty"`
	DurationS      float64 `json:"duration_s,omitempty"`
}

func publishMetrics(nc *nats.Conn, nodeID string, m Metrics) {
	payload, err := json.Marshal(m)
	if err != nil {
		log.Printf("marshal metrics: %v", err)
		return
	}
	if err := nc.Publish("veloca.metrics."+nodeID, payload); err != nil {
		log.Printf("publish metrics: %v", err)
	}
}

func publishFlow(nc *nats.Conn, toNodeID, fromNodeID string, mbps float64) {
	payload, err := json.Marshal(flowMsg{From: fromNodeID, Mbps: mbps})
	if err != nil {
		return
	}
	_ = nc.Publish("veloca.flow."+toNodeID, payload)
}

// gaugeSet holds the Prometheus gauges backing /metrics for this node.
type gaugeSet struct {
	offeredLoad prometheus.Gauge
	throughput  prometheus.Gauge
	latency     prometheus.Gauge
	queueDepth  prometheus.Gauge
	packetLoss  prometheus.Gauge
}

func newGaugeSet(nodeID string) *gaugeSet {
	labels := prometheus.Labels{"node": nodeID}
	return &gaugeSet{
		offeredLoad: promauto.NewGauge(prometheus.GaugeOpts{Name: "veloca_offered_load_mbps", Help: "Simulated offered load in Mbps", ConstLabels: labels}),
		throughput:  promauto.NewGauge(prometheus.GaugeOpts{Name: "veloca_throughput_mbps", Help: "Simulated delivered throughput in Mbps", ConstLabels: labels}),
		latency:     promauto.NewGauge(prometheus.GaugeOpts{Name: "veloca_latency_ms", Help: "Simulated latency in ms", ConstLabels: labels}),
		queueDepth:  promauto.NewGauge(prometheus.GaugeOpts{Name: "veloca_queue_depth", Help: "Simulated queue depth", ConstLabels: labels}),
		packetLoss:  promauto.NewGauge(prometheus.GaugeOpts{Name: "veloca_packet_loss_pct", Help: "Simulated packet loss percentage", ConstLabels: labels}),
	}
}

func (g *gaugeSet) set(m Metrics) {
	g.offeredLoad.Set(m.OfferedLoadMbps)
	g.throughput.Set(m.ThroughputMbps)
	g.latency.Set(m.LatencyMs)
	g.queueDepth.Set(m.QueueDepth)
	g.packetLoss.Set(m.PacketLossPct)
}

func serveMetrics(addr string) {
	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.Handler())
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatalf("metrics server: %v", err)
	}
}
