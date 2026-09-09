// Command loadgen drives a synthetic traffic profile (spike, ramp, or
// plateau-only) against one or more nodes by publishing veloca.load.<node>
// messages at 1 Hz, then returns those nodes to baseline. It logs the
// exact profile it sent so later evaluation has ground truth to compare
// against.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"
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

// point is one published sample, recorded for the run's log file.
type point struct {
	TOffsetS        float64 `json:"t_offset_s"`
	Node            string  `json:"node"`
	OfferedLoadMbps float64 `json:"offered_load_mbps"`
}

type runLog struct {
	Profile   string    `json:"profile"`
	Targets   []string  `json:"targets"`
	Amplitude float64   `json:"amplitude"`
	RiseS     float64   `json:"rise_s"`
	PlateauS  float64   `json:"plateau_s"`
	FallS     float64   `json:"fall_s"`
	Seed      int64     `json:"seed"`
	StartedAt time.Time `json:"started_at"`
	EndedAt   time.Time `json:"ended_at"`
	Points    []point   `json:"points"`
}

func main() {
	profile := flag.String("profile", "spike", "load profile: spike | ramp | plateau-only")
	target := flag.String("target", "", "comma-separated node ids to load, e.g. n1,n4")
	amplitude := flag.Float64("amplitude", 2.0, "multiplier over each target's baseline throughput")
	rise := flag.Duration("rise", 3*time.Second, "ramp-up duration")
	plateau := flag.Duration("plateau", 20*time.Second, "time held at amplitude")
	fall := flag.Duration("fall", 3*time.Second, "ramp-down duration")
	seed := flag.Int64("seed", 1, "seed, recorded in the run log for reproducibility bookkeeping")
	natsURL := flag.String("nats", envOr("nats://localhost:4222", "NATS_URL"), "NATS server URL")
	topologyPath := flag.String("topology", envOr("../infra/topology.yaml", "TOPOLOGY_PATH"), "path to topology.yaml")
	logsDir := flag.String("logs-dir", envOr("../experiments/logs", "LOGS_DIR"), "directory to write the run log to")
	grafanaURL := flag.String("grafana-url", envOr("http://localhost:3000", "GRAFANA_URL"), "Grafana base URL for annotations")
	grafanaUser := flag.String("grafana-user", envOr("admin", "GRAFANA_USER"), "Grafana basic-auth user")
	grafanaPass := flag.String("grafana-pass", envOr("admin", "GRAFANA_PASS"), "Grafana basic-auth password")
	flag.Parse()

	targets := strings.Split(*target, ",")
	for i := range targets {
		targets[i] = strings.TrimSpace(targets[i])
	}
	if *target == "" || len(targets) == 0 {
		log.Fatal("--target is required, e.g. --target n1,n4")
	}

	riseS, plateauS, fallS := rise.Seconds(), plateau.Seconds(), fall.Seconds()
	if *profile == "plateau-only" {
		riseS, fallS = 0, 0
	} else if *profile != "spike" && *profile != "ramp" {
		log.Fatalf("unknown profile %q (want spike | ramp | plateau-only)", *profile)
	}
	total := riseS + plateauS + fallS

	baselines := make(map[string]float64, len(targets))
	for _, node := range targets {
		b, err := baselineThroughput(*topologyPath, node)
		if err != nil {
			log.Fatal(err)
		}
		baselines[node] = b
	}

	nc, err := nats.Connect(*natsURL, nats.Timeout(5*time.Second))
	if err != nil {
		log.Fatalf("connecting to NATS at %s: %v", *natsURL, err)
	}
	defer nc.Close()

	startedAt := time.Now()
	log.Printf("loadgen: profile=%s targets=%v amplitude=%.2f rise=%s plateau=%s fall=%s", *profile, targets, *amplitude, rise, plateau, fall)
	postAnnotation(*grafanaURL, *grafanaUser, *grafanaPass,
		fmt.Sprintf("load %s start: %s x%.1f", *profile, strings.Join(targets, ","), *amplitude),
		[]string{"veloca", "load"}, startedAt)

	rl := runLog{
		Profile: *profile, Targets: targets, Amplitude: *amplitude,
		RiseS: riseS, PlateauS: plateauS, FallS: fallS, Seed: *seed,
		StartedAt: startedAt,
	}

	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()
	tick := 0
	for {
		elapsed := float64(tick)
		mult, phase := multiplierAt(*profile, elapsed, riseS, plateauS, fallS, *amplitude)
		for _, node := range targets {
			mbps := baselines[node] * mult
			publishLoad(nc, node, mbps)
			rl.Points = append(rl.Points, point{TOffsetS: elapsed, Node: node, OfferedLoadMbps: mbps})
		}
		log.Printf("t=%5.1fs phase=%-8s multiplier=%.2f", elapsed, phase, mult)
		if elapsed >= total {
			break
		}
		<-ticker.C
		tick++
	}

	rl.EndedAt = time.Now()
	postAnnotation(*grafanaURL, *grafanaUser, *grafanaPass,
		fmt.Sprintf("load %s end: %s", *profile, strings.Join(targets, ",")),
		[]string{"veloca", "load"}, rl.EndedAt)

	if err := writeRunLog(*logsDir, rl); err != nil {
		log.Printf("writing run log: %v", err)
	}
	log.Printf("loadgen: done, targets back at baseline")
}

func publishLoad(nc *nats.Conn, node string, mbps float64) {
	payload, err := json.Marshal(struct {
		OfferedLoadMbps float64 `json:"offered_load_mbps"`
	}{OfferedLoadMbps: mbps})
	if err != nil {
		return
	}
	if err := nc.Publish("veloca.load."+node, payload); err != nil {
		log.Printf("publish load to %s: %v", node, err)
	}
}

// multiplierAt returns the offered-load multiplier (1.0 = baseline) at a
// given elapsed second, and a label for the current phase. "ramp" uses an
// eased (smoothstep) transition; "spike" uses a straight line — the same
// shape, just steeper because rise/fall are typically shorter.
func multiplierAt(profile string, elapsed, riseS, plateauS, fallS, amplitude float64) (float64, string) {
	total := riseS + plateauS + fallS
	switch {
	case elapsed < riseS:
		frac := 1.0
		if riseS > 0 {
			frac = elapsed / riseS
		}
		if profile == "ramp" {
			frac = smoothstep(frac)
		}
		return 1 + (amplitude-1)*frac, "rise"
	case elapsed < riseS+plateauS:
		return amplitude, "plateau"
	case elapsed < total:
		frac := 1.0
		if fallS > 0 {
			frac = (elapsed - riseS - plateauS) / fallS
		}
		if profile == "ramp" {
			frac = smoothstep(frac)
		}
		return amplitude - (amplitude-1)*frac, "fall"
	default:
		return 1, "done"
	}
}

func smoothstep(x float64) float64 {
	if x < 0 {
		x = 0
	}
	if x > 1 {
		x = 1
	}
	return x * x * (3 - 2*x)
}

func writeRunLog(dir string, rl runLog) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	name := fmt.Sprintf("load_%s.json", rl.StartedAt.UTC().Format("20060102T150405Z"))
	path := filepath.Join(dir, name)
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	enc := json.NewEncoder(f)
	enc.SetIndent("", "  ")
	if err := enc.Encode(rl); err != nil {
		return err
	}
	log.Printf("loadgen: wrote %s", path)
	return nil
}
