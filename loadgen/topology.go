package main

import (
	"fmt"
	"os"

	"gopkg.in/yaml.v3"
)

type topologyNode struct {
	ID       string `yaml:"id"`
	Baseline struct {
		ThroughputMbps float64 `yaml:"throughput_mbps"`
	} `yaml:"baseline"`
}

type topologyFile struct {
	Nodes []topologyNode `yaml:"nodes"`
}

// baselineThroughput loads infra/topology.yaml just far enough to answer
// "what does this node normally push?" — the number a load profile's
// amplitude multiplies.
func baselineThroughput(path, nodeID string) (float64, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, fmt.Errorf("reading topology %s: %w", path, err)
	}
	var t topologyFile
	if err := yaml.Unmarshal(data, &t); err != nil {
		return 0, fmt.Errorf("parsing topology %s: %w", path, err)
	}
	for _, n := range t.Nodes {
		if n.ID == nodeID {
			return n.Baseline.ThroughputMbps, nil
		}
	}
	return 0, fmt.Errorf("node %q not found in topology %s", nodeID, path)
}
