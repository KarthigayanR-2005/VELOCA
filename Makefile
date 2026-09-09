.PHONY: up down logs surge chaos-kill

# On Windows/git-bash, make's recipe shell drops $APPDATA, which `go`
# needs to find its persisted env config (and thus its default GOPATH) —
# so `go run` fails inside a Makefile recipe unless we pin these directly.
# Adjust if this repo moves to a different machine/user.
export GOPATH := C:/Users/karth/go
export GOMODCACHE := C:/Users/karth/go/pkg/mod
export GOCACHE := C:/Users/karth/AppData/Local/go-build
export TMP := C:/Users/karth/AppData/Local/Temp
export TEMP := C:/Users/karth/AppData/Local/Temp

up:
	docker compose -f infra/docker-compose.yml up --build -d

down:
	docker compose -f infra/docker-compose.yml down

logs:
	docker compose -f infra/docker-compose.yml logs -f

# Demo scenario: spike n1 and n4 to 3.5x baseline, with a loss fault on
# n2-n3 (which sits on the ring path between them) starting 5s in. Runs
# both CLIs from the host against the compose NATS on localhost:4222.
surge:
	(cd loadgen && go run . --profile spike --target n1,n4 --amplitude 3.5 --rise 3s --plateau 20s --fall 3s --seed 42) & \
	(cd chaos && go run . loss n2-n3 --pct 15 --at 5s --for 20s) & \
	wait

# make chaos-kill NODE=n3
chaos-kill:
	cd chaos && go run . kill $(NODE) --at 0s
