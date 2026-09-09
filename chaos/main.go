// Command chaos injects one fault into the running simulation:
//
//	chaos kill n3 --at 10s
//	chaos latency n2 --ms 80 --at 5s --for 30s
//	chaos loss n2-n3 --pct 15 --at 5s --for 30s
//
// It waits --at, fires the fault by publishing to veloca.chaos.<node>,
// records it in experiments/logs/ground_truth.jsonl (the answer key for
// later evaluation), and exits — the agent itself expires latency/loss
// after --for, and never un-kills a killed node.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	"github.com/nats-io/nats.go"
)

func envOr(fallback, key string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// chaosMsg mirrors agent/metrics.go's wire format exactly.
type chaosMsg struct {
	Type           string  `json:"type"`
	Target         string  `json:"target"`
	ExtraLatencyMs float64 `json:"extra_latency_ms,omitempty"`
	LossPct        float64 `json:"loss_pct,omitempty"`
	DurationS      float64 `json:"duration_s,omitempty"`
}

func usage() {
	fmt.Fprintln(os.Stderr, `usage:
  chaos kill <node> [--at 10s]
  chaos latency <node> --ms 80 --for 30s [--at 5s]
  chaos loss <n1-n2> --pct 15 --for 30s [--at 5s]`)
	os.Exit(2)
}

func main() {
	if len(os.Args) < 3 {
		usage()
	}
	cmd := os.Args[1]
	target := os.Args[2]

	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	at := fs.Duration("at", 0, "delay before firing")
	forDur := fs.Duration("for", 0, "how long the effect stays active (latency/loss only)")
	ms := fs.Float64("ms", 0, "extra latency in ms (latency only)")
	pct := fs.Float64("pct", 0, "extra packet loss percent (loss only)")
	natsURL := fs.String("nats", envOr("nats://localhost:4222", "NATS_URL"), "NATS server URL")
	logsDir := fs.String("logs-dir", envOr("../experiments/logs", "LOGS_DIR"), "directory to append ground_truth.jsonl to")
	grafanaURL := fs.String("grafana-url", envOr("http://localhost:3000", "GRAFANA_URL"), "Grafana base URL for annotations")
	grafanaUser := fs.String("grafana-user", envOr("admin", "GRAFANA_USER"), "Grafana basic-auth user")
	grafanaPass := fs.String("grafana-pass", envOr("admin", "GRAFANA_PASS"), "Grafana basic-auth password")
	if err := fs.Parse(os.Args[3:]); err != nil {
		usage()
	}

	var subject string
	msg := chaosMsg{Type: cmd, Target: target}
	params := map[string]any{}

	switch cmd {
	case "kill":
		subject = "veloca.chaos." + target
	case "latency":
		if *ms <= 0 || *forDur <= 0 {
			log.Fatal("latency requires --ms and --for")
		}
		subject = "veloca.chaos." + target
		msg.ExtraLatencyMs = *ms
		msg.DurationS = forDur.Seconds()
		params["extra_latency_ms"] = *ms
	case "loss":
		if *pct <= 0 || *forDur <= 0 {
			log.Fatal("loss requires --pct and --for")
		}
		parts := strings.SplitN(target, "-", 2)
		if len(parts) != 2 {
			log.Fatalf("loss target must be a link like n2-n3, got %q", target)
		}
		subject = "veloca.chaos." + parts[0]
		msg.LossPct = *pct
		msg.DurationS = forDur.Seconds()
		params["loss_pct"] = *pct
	default:
		usage()
	}

	nc, err := nats.Connect(*natsURL, nats.Timeout(5*time.Second))
	if err != nil {
		log.Fatalf("connecting to NATS at %s: %v", *natsURL, err)
	}
	defer nc.Close()

	if *at > 0 {
		log.Printf("chaos: waiting %s before firing %s %s", at, cmd, target)
		time.Sleep(*at)
	}
	firedAt := time.Now()

	payload, err := json.Marshal(msg)
	if err != nil {
		log.Fatalf("marshal chaos message: %v", err)
	}
	if err := nc.Publish(subject, payload); err != nil {
		log.Fatalf("publish: %v", err)
	}
	nc.Flush()
	log.Printf("chaos: fired %s %s -> %s", cmd, target, subject)

	rec := groundTruthRecord{
		Ts: rfc3339(firedAt), Type: cmd, Target: target,
		Params: params, DurationS: msg.DurationS,
	}
	if err := appendGroundTruth(*logsDir, rec); err != nil {
		log.Printf("writing ground_truth.jsonl: %v", err)
	}

	text := fmt.Sprintf("chaos: %s %s", cmd, target)
	if cmd == "latency" {
		text = fmt.Sprintf("chaos: latency %s +%.0fms for %s", target, *ms, forDur)
	} else if cmd == "loss" {
		text = fmt.Sprintf("chaos: loss %s %.0f%% for %s", target, *pct, forDur)
	}
	postAnnotation(*grafanaURL, *grafanaUser, *grafanaPass, text, []string{"veloca", "chaos"}, firedAt)
}
