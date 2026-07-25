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
  --metadata-from-file=startup-script=infra/gcp/startup-script.sh
```

infra/gcp/startup-script.sh installs Docker CE, the compose plugin, and
the `at`/`atd` job scheduler (used later for synthetic traffic) via apt
on first boot.

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

The uptime monitors only hit /health/live (and, since 2026-07-12,
/health/ready), neither of which exercises the pipeline or produces a
request-volume number on their own. infra/gcp/synthetic_traffic.sh sends
real /chat requests through the whole pipeline (Kafka -> RAG -> Ollama ->
SQLite), tagged with tenant_id "synthetic-monitor" so they're clearly
separate from any real usage, and then polls GET /chat/{request_id}
until the request actually finishes, logging the real outcome
(completed, failed, or timeout) rather than just the accept response.
That distinction matters: the gateway returns 200 the instant it
publishes to Kafka, before any of the real work happens, so only
checking the accept call would miss a broken downstream pipeline
entirely.

infra/gcp/daily_scheduler.sh runs once a day via cron and picks 8
randomized times to queue synthetic_traffic.sh with `at`, instead of a
fixed interval:

```bash
# crontab -l on the VM:
5 0 * * * /home/hilalfelix/scripts/daily_scheduler.sh
```

It splits the day into 8 three-hour windows and picks a random minute
inside each one, so the times land somewhere different every day rather
than on the hour. This replaced an earlier fixed `0 */3 * * *` cron
entry on 2026-07-12 - same volume, less mechanical-looking pattern.
Needs `at`/`atd` installed and running, which the startup script handles
on a fresh VM (`sudo apt-get install -y at`, `sudo systemctl enable --now
atd` if setting it up by hand on an existing one).

Each run appends one line to ~/synthetic_traffic.log, for example:

```
[2026-07-12T17:34:37Z] request_id=3aed7410-... accept_status=200 outcome=completed poll_elapsed=50s total_elapsed=51.6s
```

To pull the log down:

```bash
gcloud compute scp ai-platform-vm:~/synthetic_traffic.log ./synthetic_traffic.log \
  --zone=us-central1-a --tunnel-through-iap
```

Started 2026-07-10, running 8x/day. Over the 30-day window that's roughly
240 real end-to-end pipeline executions, giving a real "N requests, X%
completed successfully, average latency" figure computed from the log
rather than asserted.

### Secrets on the VM

The production AI_PLATFORM_API_KEY lives only in
`~/ai-platform-builder/.env` on the VM, generated with
`openssl rand -hex 24`. It's never in git. A copy is kept locally at
`.prod_api_key_DO_NOT_COMMIT.txt` (gitignored) purely as a record for the
project owner; that file must never be committed.

### Monitoring, and where the numbers live

Two endpoints are monitored, not one, because they check different
things. /health/live only confirms the gateway process is up and
answering HTTP - it doesn't touch Kafka, Ollama, or the database, so it
would stay green even if the pipeline behind it were completely broken.
/health/ready actually checks Kafka and database connectivity. Added
2026-07-12 after noticing the gap.

1. GCP Cloud Monitoring (primary): uptime check
   `ai-platform-gateway-uptime` hits /health/live every 5 minutes, and
   `ai-platform-gateway-ready` hits /health/ready on the same interval,
   both from Google's global probers, each with its own alert policy
   emailing sujon2100@gmail.com on failure. View or export at
   `https://console.cloud.google.com/monitoring/uptime?project=ai-platform-eb2-demo`.
2. UptimeRobot (independent third-party check): "AI Platform Gateway"
   monitors /health/live, "AI Platform Gateway (readiness)" monitors
   /health/ready, same 5-minute interval. Public status page, no login
   required: `https://stats.uptimerobot.com/2JUsdtF71z` - this is the
   link to hand to a paralegal. The dashboard also has an export button
   for a downloadable record.
3. Synthetic traffic against /chat (see above) is the strongest signal
   of the three - it's the only one that proves the actual claimed
   system (LLM orchestration, RAG, async Kafka workflow) is doing real
   work, not just that a web server responds.
4. The app's own Prometheus at port 9090 isn't exposed publicly. View it
   through an IAP-forwarded tunnel:
   `gcloud compute ssh ai-platform-vm --zone=us-central1-a --tunnel-through-iap -- -L 9090:localhost:9090`
   then open localhost:9090. Has request counts and latency histograms
   per service.

### Weekly check-in, running natively on the VM

Originally the weekly check-in (pulling uptime numbers, summarizing,
logging) ran as a Claude Code scheduled task. That only fires while the
Claude app is open, so it went quiet for several days when the laptop
stayed closed. Moved on 2026-07-24 to a cron job on the VM itself, which
runs regardless of whether anyone's laptop or Claude session is open.

infra/gcp/weekly_checkin.sh hits both health endpoints locally, queries
GCP Cloud Monitoring and the UptimeRobot API directly, and appends a
dated block to ~/weekly_checkin.log on the VM:

```bash
# crontab -l on the VM:
17 9 * * 5 /home/hilalfelix/scripts/weekly_checkin.sh
```

It authenticates to GCP as a dedicated service account,
monitoring-reader@ai-platform-eb2-demo.iam.gserviceaccount.com, created
specifically for this and granted only roles/monitoring.viewer - it
can't touch the VM, can't modify anything, can only read monitoring
data. The key file lives at ~/.gcp/monitoring-reader-key.json on the VM,
outside the repo, same treatment as every other secret here. UptimeRobot
access uses a read-only API key (not the main key, which can edit or
delete monitors), stored in .env alongside the production API key.

This only handles data collection and local logging. Pulling the VM's
log into this repo and committing it stays a manual, reviewed step -
same standing rule as everywhere else in this project. Autonomous git
push from a VM cron job was considered and deliberately rejected: it
would mean a GitHub-write credential living permanently on a
publicly-reachable machine, and it would skip the review step that has
already caught real problems before they landed (see the merge conflict
with the codex bot's stub code, resolved by hand rather than
auto-merged). To pull the latest check-in data:

```bash
gcloud compute ssh ai-platform-vm --zone=us-central1-a --tunnel-through-iap --command="cat ~/weekly_checkin.log"
```

### Issues found and fixed

Worth keeping in the record rather than glossing over.

1. Silent Kafka publish failure (found 2026-07-10, before the monitoring
   window started). KafkaProducer.flush() only waits for pending batches
   to resolve, not to succeed - a failed send still counts as resolved.
   The gateway was reporting "accepted" even when the underlying publish
   had failed. Fixed by checking the Future returned by send() directly
   (future.get(timeout=5)), which now correctly surfaces as a 503
   instead of a false "accepted". See services/api-gateway/main.py.
2. Health endpoint didn't support HEAD (found 2026-07-10, before the
   monitoring window started). FastAPI's @app.get doesn't register HEAD
   automatically, and UptimeRobot probes with HEAD by default. Showed up
   as a real "down" reading in UptimeRobot that was a monitoring
   artifact, not an actual outage. Fixed by switching /health/live and
   /health/ready to @app.api_route(..., methods=["GET", "HEAD"]).
3. Ollama completion timeout too short for this hardware (found
   2026-07-24, during the monitoring window - this one happened live,
   not before the window started). Synthetic traffic showed a 14.6%
   failure rate (14 of 96 polled requests) over the prior two weeks.
   Root cause: this e2-small VM runs Ollama on CPU only, generating at
   roughly 3.3 tokens/second. The 60 second per-attempt timeout in
   services/llm-orchestrator/router.py (OLLAMA_TIMEOUT_SECONDS) was
   killing legitimate, still-in-progress generations on longer
   responses, not actual hangs. Every one of the 14 failures resolved at
   almost exactly 120 seconds of polling, which is 2 attempts x the old
   60s timeout - a clean signature of the timeout truncating a working
   call rather than the pipeline being broken. Fixed by raising
   OLLAMA_TIMEOUT_SECONDS to 220 seconds rather than upsizing the VM,
   since the model works fine, it just needs more time on this hardware.
   Deployed 2026-07-24. Verified with a 12-request post-fix batch: 12/12
   completed, 0 failed, versus 14/96 (14.6%) failed before the fix. Some
   individual requests still took up to 6-7 minutes end to end when a
   first attempt used the full 220s before a successful retry - that's
   expected on CPU-only inference at this VM size, not a new problem.
   See docs/monitoring_log.md for the full before-and-after writeup -
   the pre-fix number stays in the record rather than being erased,
   since a documented before-and-after is stronger evidence than a
   clean number with no history.
4. Fixing #3 exposed that the synthetic traffic poller's own wait
   ceiling (POLL_TIMEOUT_SECONDS in infra/gcp/synthetic_traffic.sh) was
   too short to observe the new worst case: MAX_ATTEMPTS=2 x the new
   220s timeout is up to 440s, longer than the poller's 300s window at
   the time. This caused genuinely successful requests to be logged as
   outcome=timeout - a false negative in the test harness, not a real
   failure. Confirmed by checking the database directly: every request
   the poller had logged as "timeout" had actually completed. Fixed by
   raising POLL_TIMEOUT_SECONDS to 480s. Deployed 2026-07-24.

The first two issues were fixed and redeployed before the 30-day
monitoring window was considered started. The third and fourth happened
live, mid-window, and are reported as exactly that: real issues, caught
by the monitoring that was already running, fixed, and verified rather
than hidden.

5. Consumer group instability under CPU pressure, causing redundant
   reprocessing of already-completed messages (found 2026-07-24 while
   validating #3 and #4, root-caused and fixed later the same day after
   a second, separate incident made clear it wasn't a one-off). Two
   uptime incidents on 2026-07-24 - 19:04-19:16 UTC and 22:44-22:51 UTC,
   same signature both times - had /health/live and /health/ready fail
   together, which pointed at something affecting the whole VM rather
   than a single dependency, since /health/live has no dependency checks
   at all. Root cause: this e2-small instance has 2 vCPUs and no
   per-container CPU limit on Ollama. A single generation - longer now
   that OLLAMA_TIMEOUT_SECONDS is 220 rather than 60 - can consume the
   entire machine's CPU, starving Docker's own DNS resolution (confirmed
   in the systemd journal: `DNS lookup failed for redpanda:9092` during
   both incident windows), redpanda's client connections, and the
   gateway's ability to answer health checks in time. The same CPU
   starvation was also causing the workflow-engine's Kafka consumer to
   miss heartbeats and get dropped from its consumer group; because
   Kafka's automatic offset commits were failing for the same reason,
   the consumer would rejoin from a stale offset and silently re-process
   a batch of messages that had already completed hours earlier -
   confirmed directly: of 14 distinct requests completing in one
   20-minute window, 13 were reprocessed duplicates of an earlier
   validation batch, with only 1 genuinely new request sent in that
   window. Fixed with two changes: capped the ollama container to 1.0 of
   the VM's 2 vCPUs (docker-compose.yml, `cpus: "1.0"`), verified via the
   container's cgroup cpu.stat showing real enforced throttling, not
   just a configured-but-ignored limit; and switched the Kafka consumer
   from automatic to manual offset commits with a raised
   max_poll_interval_ms (services/workflow-engine/worker.py), so the
   committed offset only advances once a message is actually done
   regardless of CPU pressure elsewhere, and a legitimately slow retry
   sequence (worst case around 22 minutes with the 220s timeout) doesn't
   get mistaken for a dead consumer under the old 5-minute default.
   Deployed 2026-07-24 23:29 UTC. Verified: consumer group went from
   Empty/0 members to Stable/1 member, with the committed offset
   advancing correctly as real work completed. See
   docs/monitoring_log.md for the full investigation with exact
   timestamps and log excerpts. Not claimed as a complete fix for the
   underlying constraint - the VM is still only 2 vCPUs, and the cap
   trades some Ollama latency for system-wide responsiveness. If the
   same signature recurs with these changes in place, that points at
   the 2-vCPU ceiling itself, and upsizing the VM is the next real
   option - a cost decision for the project owner, not something to do
   unilaterally mid-window.

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
