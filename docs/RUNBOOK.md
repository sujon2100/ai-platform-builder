# Runbook: local testing and cloud deployment

Reference for running this locally and for redeploying/tearing down the
cloud copy. Written so it can be followed from scratch after a long gap
without having to relearn the setup.

## Part 1: local (Docker Compose)

### Prerequisites

- Docker Desktop installed and running (`docker info` should succeed)
- About 2GB free disk for images plus the Ollama model
- Terminal, in the repo root

### One-time setup

```bash
cd ai-platform-builder
cp .env.example .env          # edit AI_PLATFORM_API_KEY if you want something other than the default
```

If Docker Desktop isn't running:

```bash
open -a Docker
until docker info >/dev/null 2>&1; do sleep 5; done
```

### Build the images

```bash
docker compose build
```

### Bring the stack up, in dependency order

Redpanda and Ollama need to be up (and the model pulled) before the app
services will do anything useful.

```bash
# broker + LLM runtime
docker compose up -d redpanda ollama

# wait for redpanda to report healthy
docker inspect --format='{{.State.Health.Status}}' redpanda
# repeat until it prints "healthy"

# pull the model (one time only, cached in the ollama_data volume)
docker exec ollama ollama pull qwen2.5:0.5b
docker exec ollama ollama list

# app services + local prometheus
docker compose up -d api-gateway workflow-engine prometheus

docker compose ps
```

### Smoke test

```bash
source .env

curl -s http://localhost:8000/health/live
curl -s http://localhost:8000/health/ready

# no api key, should 401
curl -s -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"demo-tenant","message":"hello"}'

# real request, async - returns immediately with a request_id
curl -s -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -H "x-api-key: $AI_PLATFORM_API_KEY" \
  -d '{"tenant_id":"demo-tenant","message":"What happens on repeated failures?"}'

# poll for the result. first call after a fresh container start is a cold
# start, can take 30-40s while Ollama loads the model. warm calls after
# that run around 3-7s.
curl -s http://localhost:8000/chat/<request_id> -H "x-api-key: $AI_PLATFORM_API_KEY"

curl -s http://localhost:8000/metrics | grep ai_requests_total

open http://localhost:9090/targets
```

### Simulating a failure

```bash
docker stop ollama
docker logs -f workflow-engine
# watch the retries, circuit breaker opening, DLQ routing

docker exec redpanda rpk topic consume ai-chat-dlq -n 1

docker start ollama
# workflow-engine reconnects on its own, next request succeeds once the model is warm again
```

### What to record from a local run

- `docker stats --no-stream` for CPU/memory per container
- `curl -s http://localhost:8000/metrics` for request counts and latency
- `docker compose ps` to confirm nothing restarted unexpectedly
- anything unexpected in `docker logs <container>`, copied verbatim

See `local_test_results.md` for the baseline run from 2026-07-10.

### Tear down

```bash
docker compose stop           # keeps images and volumes for next time
docker compose down -v        # full wipe, including the model and SQLite data
```

## Part 2: cloud deployment

Live on GCP since 2026-07-10, in a dedicated project (`ai-platform-eb2-demo`),
sized from the local numbers above (about 1GB in use, so e2-small with
2 vCPU / 2GB RAM gives comfortable headroom).

- Public endpoint: `http://35.255.55.28:8000`
- Project: `ai-platform-eb2-demo` (account sujon2100@gmail.com)
- VM: `ai-platform-vm`, zone `us-central1-a`, machine type `e2-small`
- Static IP: `ai-platform-ip`, reserved so the address doesn't change on restart

### One-time account setup

1. Create a GCP account, activate the free trial ($300 / 90 days)
2. Create a dedicated project rather than reusing a shared one
   (console -> project dropdown -> New Project -> `ai-platform-eb2-demo`)
3. Enable the Compute Engine API for that project
4. Set a budget alert (Billing -> Budgets & alerts), scoped to the
   project, threshold around $30/month
5. Install the CLI: `brew install --cask google-cloud-sdk`
6. `gcloud auth login`
7. `gcloud config set project ai-platform-eb2-demo`
8. `gcloud config set compute/region us-central1`
9. `gcloud config set compute/zone us-central1-a`

### Provisioning

```bash
gcloud compute addresses create ai-platform-ip --region=us-central1

# ssh only through the iap tunnel, no port 22 open to the internet.
# gateway port stays open publicly since uptime monitors need to reach it.
gcloud compute firewall-rules create allow-ssh-iap \
  --network=default --direction=INGRESS --action=ALLOW \
  --rules=tcp:22 --source-ranges=35.235.240.0/20 \
  --target-tags=ai-platform-vm

gcloud compute firewall-rules create allow-gateway-http \
  --network=default --direction=INGRESS --action=ALLOW \
  --rules=tcp:8000 --source-ranges=0.0.0.0/0 \
  --target-tags=ai-platform-vm

gcloud compute instances create ai-platform-vm \
  --zone=us-central1-a --machine-type=e2-small \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-standard \
  --address=ai-platform-ip --tags=ai-platform-vm \
  --metadata-from-file=startup-script=startup-script.sh
```

`startup-script.sh` installs Docker CE and the compose plugin via apt on
first boot.

### Connecting to the VM

No public SSH port, so this always goes through the IAP tunnel:

```bash
gcloud compute ssh ai-platform-vm --zone=us-central1-a --tunnel-through-iap
```

### Redeploying after a code change

```bash
tar --exclude='.git' --exclude='__pycache__' --exclude='.env' \
    --exclude='.prod_api_key_DO_NOT_COMMIT.txt' \
    -czf /tmp/ai-platform-builder.tar.gz .

gcloud compute scp /tmp/ai-platform-builder.tar.gz ai-platform-vm:/tmp/ \
  --zone=us-central1-a --tunnel-through-iap

# on the VM:
tar -xzf /tmp/ai-platform-builder.tar.gz -C ~/ai-platform-builder
cd ~/ai-platform-builder
sudo docker compose build api-gateway workflow-engine
sudo docker compose up -d api-gateway workflow-engine
```

Redpanda and Ollama only need rebuilding if their config in
docker-compose.yml changes. Normal code changes only touch api-gateway
and workflow-engine.

### Synthetic traffic

The uptime monitors only hit /health/live, they don't exercise the
pipeline or produce any request-volume number on their own. A cron job on
the VM sends real /chat requests through the whole pipeline (Kafka -> RAG
-> Ollama -> SQLite) every 3 hours, tagged with tenant_id
"synthetic-monitor" so they're clearly separate from any real usage:

```bash
# ~/scripts/synthetic_traffic.sh on the VM
# crontab -l:
0 */3 * * * /home/hilalfelix/scripts/synthetic_traffic.sh
```

Each run appends one line to ~/synthetic_traffic.log with timestamp,
HTTP status, and gateway accept latency. To pull it down:

```bash
gcloud compute scp ai-platform-vm:~/synthetic_traffic.log ./synthetic_traffic.log \
  --zone=us-central1-a --tunnel-through-iap
```

Started 2026-07-10, running 8x/day. Over the 30-day window that's roughly
240 real end-to-end pipeline executions, giving a usage number computed
from the log rather than just asserted.

### Secrets on the VM

The production AI_PLATFORM_API_KEY lives only in
`~/ai-platform-builder/.env` on the VM, generated with
`openssl rand -hex 24`. It's never in git. A copy is kept locally at
`.prod_api_key_DO_NOT_COMMIT.txt` (gitignored) purely as a record for the
project owner; that file must never be committed.

### Monitoring, and where the numbers live

1. GCP Cloud Monitoring (primary): uptime check
   `ai-platform-gateway-uptime` hits /health/live every 5 minutes from
   Google's global probers, with an alert policy emailing
   sujon2100@gmail.com on failure. View or export at
   `https://console.cloud.google.com/monitoring/uptime?project=ai-platform-eb2-demo`.
2. UptimeRobot (independent third-party check): same endpoint, same
   interval. Public status page, no login required:
   `https://stats.uptimerobot.com/2JUsdtF71z` - this is the link to hand
   to a paralegal. The dashboard also has an export button for a
   downloadable record.
3. The app's own Prometheus at port 9090 isn't exposed publicly. View it
   through an IAP-forwarded tunnel:
   `gcloud compute ssh ai-platform-vm --zone=us-central1-a --tunnel-through-iap -- -L 9090:localhost:9090`
   then open localhost:9090. Has request counts and latency histograms
   per service.

### Issues found and fixed during initial deployment (2026-07-10)

Worth keeping in the record rather than glossing over, since these
happened before the monitoring window officially started.

1. Silent Kafka publish failure. KafkaProducer.flush() only waits for
   pending batches to resolve, not to succeed - a failed send still
   counts as resolved. The gateway was reporting "accepted" even when the
   underlying publish had failed. Fixed by checking the Future returned
   by send() directly (future.get(timeout=5)), which now correctly
   surfaces as a 503 instead of a false "accepted". See
   services/api-gateway/main.py.
2. Health endpoint didn't support HEAD. FastAPI's @app.get doesn't
   register HEAD automatically, and UptimeRobot probes with HEAD by
   default. Showed up as a real "down" reading in UptimeRobot that was a
   monitoring artifact, not an actual outage. Fixed by switching
   /health/live and /health/ready to
   @app.api_route(..., methods=["GET", "HEAD"]).

Both were fixed and redeployed before the 30-day monitoring window was
considered started - see the check-in log for the actual start
timestamp.

### Teardown

```bash
gcloud compute instances delete ai-platform-vm --zone=us-central1-a
gcloud compute addresses delete ai-platform-ip --region=us-central1
gcloud compute firewall-rules delete allow-ssh-iap allow-gateway-http

# or, for one clean sweep of everything including the uptime check,
# alert policy, and budget:
gcloud projects delete ai-platform-eb2-demo
```

Deleting the project is the simplest complete teardown. The GitHub repo
and local files (test results, the final writeup) are unaffected.
