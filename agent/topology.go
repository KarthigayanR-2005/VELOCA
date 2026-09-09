package main

import (
	"log"
	"math"
	"os"

	"gopkg.in/yaml.v3"
)

// Baseline is the steady-state metric values a node's simulated traffic
// hovers around. Loaded from infra/topology.yaml.
type Baseline struct {
	ThroughputMbps float64 `yaml:"throughput_mbps"`
	LatencyMs      float64 `yaml:"latency_ms"`
	QueueDepth     float64 `yaml:"queue_depth"`
	PacketLossPct  float64 `yaml:"packet_loss_pct"`
}

type topologyNode struct {
	ID       string   `yaml:"id"`
	Baseline Baseline `yaml:"baseline"`
}

type topologyLink struct {
	From          string  `yaml:"from"`
	To            string  `yaml:"to"`
	BandwidthMbps float64 `yaml:"bandwidth_mbps"`
	BaseLatencyMs float64 `yaml:"base_latency_ms"`
}

type topologyFile struct {
	Nodes []topologyNode `yaml:"nodes"`
	Links []topologyLink `yaml:"links"`
}

// neighbor is one link-adjacent peer of this node.
type neighbor struct {
	PeerID        string
	LinkName      string // "n2-n3", exactly as written in topology.yaml
	BandwidthMbps float64
}

func loadTopologyFile(path string) topologyFile {
	data, err := os.ReadFile(path)
	if err != nil {
		log.Fatalf("reading topology %s: %v", path, err)
	}
	var t topologyFile
	if err := yaml.Unmarshal(data, &t); err != nil {
		log.Fatalf("parsing topology %s: %v", path, err)
	}
	return t
}

func findBaseline(t topologyFile, nodeID string) Baseline {
	for _, n := range t.Nodes {
		if n.ID == nodeID {
			return n.Baseline
		}
	}
	log.Fatalf("node %q not found in topology", nodeID)
	return Baseline{}
}

// neighborsOf returns every link incident to nodeID, plus this node's
// capacity: the bandwidth of its weakest attached link. That weakest link
// is the node's bottleneck — traffic can't leave faster than it allows.
func neighborsOf(t topologyFile, nodeID string) (neighbors []neighbor, capacityMbps float64) {
	capacityMbps = math.MaxFloat64
	for _, l := range t.Links {
		var peer string
		switch nodeID {
		case l.From:
			peer = l.To
		case l.To:
			peer = l.From
		default:
			continue
		}
		neighbors = append(neighbors, neighbor{PeerID: peer, LinkName: linkName(l), BandwidthMbps: l.BandwidthMbps})
		if l.BandwidthMbps < capacityMbps {
			capacityMbps = l.BandwidthMbps
		}
	}
	if len(neighbors) == 0 {
		log.Fatalf("node %q has no links in topology", nodeID)
	}
	return neighbors, capacityMbps
}

func linkName(l topologyLink) string { return l.From + "-" + l.To }

// neighborForLink resolves a chaos target like "n2-n3" (as typed by an
// operator, in either direction) to the neighbor peer ID it refers to.
func neighborForLink(neighbors []neighbor, nodeID, linkTarget string) (peerID string, ok bool) {
	for _, nb := range neighbors {
		if nb.LinkName == linkTarget || nb.PeerID+"-"+nodeID == linkTarget {
			return nb.PeerID, true
		}
	}
	return "", false
}
