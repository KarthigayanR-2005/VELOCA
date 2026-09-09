package main

import (
	"os"

	"gopkg.in/yaml.v3"
)

// Link is one edge of the simulated mesh.
type Link struct {
	From          string  `yaml:"from"`
	To            string  `yaml:"to"`
	BandwidthMbps float64 `yaml:"bandwidth_mbps"`
	BaseLatencyMs float64 `yaml:"base_latency_ms"`
}

type topologyNode struct {
	ID string `yaml:"id"`
}

// Topology is infra/topology.yaml, parsed just enough to know which node
// IDs to expect. Baselines live with the agents; the control-plane only
// cares about identity and liveness.
type Topology struct {
	Nodes []topologyNode `yaml:"nodes"`
	Links []Link         `yaml:"links"`
}

func (t Topology) NodeIDs() []string {
	ids := make([]string, len(t.Nodes))
	for i, n := range t.Nodes {
		ids[i] = n.ID
	}
	return ids
}

func loadTopology(path string) (Topology, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Topology{}, err
	}
	var t Topology
	if err := yaml.Unmarshal(data, &t); err != nil {
		return Topology{}, err
	}
	return t, nil
}
