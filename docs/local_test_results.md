# Local test results (Docker Compose)

Date: 2026-07-10
Host: macOS, Docker Desktop 28.3.3, x86_64
Stack: redpanda, ollama (qwen2.5:0.5b), api-gateway, workflow-engine, prometheus

Baseline run before touching the cloud deployment. Numbers here are for
comparison against the cloud numbers later, not the evidence figures
themselves.

## What was exercised

- GET /health/live and GET /health/ready both return 200.
- POST /chat with no API key gets rejected with 401.
- POST /chat with a valid key flows through the whole pipeline: event
  published to Redpanda, picked up by workflow-engine, enriched with the
  local TF-IDF retrieval, sent to Ollama, response persisted to SQLite,
  and retrievable via GET /chat/{request_id}.
- GET /metrics returns Prometheus-format counters and histograms, and
  Prometheus itself confirms the scrape target as up.
- Failure injection: stopped the ollama container mid-run. workflow-engine
  retried 3 times with backoff (2s, 4s, 8s), opened the circuit breaker
  after 3 consecutive failures, and routed the event to the ai-chat-dlq
  topic. The request's stored status correctly shows "failed" - it isn't
  silently dropped or reported as success.
- Recovery: restarted ollama. The first two requests after restart still
  timed out at 30s because the model had to reload into memory - a real
  cold-start-after-restart case, not a hypothetical one. Once the model
  was warm again (confirmed with a direct curl to ollama, ~4s response),
  the next request completed normally end to end.

## Latency (8 requests total, includes 1 cold start and 1 failed/DLQ request)

Gateway-side latency (accept + enqueue only) averaged about 18ms, all
requests under 100ms - the endpoint only validates and enqueues, it
doesn't wait on the LLM. End-to-end async processing (enqueue to
completed) was 3-7 seconds once the model was warm, and about 39 seconds
on the very first request while Ollama loaded the model. The two requests
right after the container restart timed out at 30s each before the
service recovered.

## Resource usage (docker stats, steady state after a few requests)

redpanda used about 190MB, ollama with the model loaded used about
558MB, workflow-engine about 141MB, api-gateway about 63MB, and
prometheus about 44MB. Total across the stack: roughly 1GB with the LLM
loaded. This number is what drove the cloud instance size - see the
deployment notes for details.

## Limitations of this run

This was a short validation run, around 15 minutes, not a reliability
trial - it confirms the pipeline works end to end and that failures get
reported honestly, but says nothing about long-run uptime. The 30s Ollama
HTTP timeout in services/llm-orchestrator/router.py is tight relative to
cold-start reload time, which is worth watching if VM reboots turn out to
be common. SQLite for result storage is fine for a single instance at low
traffic; it isn't concurrent-safe at scale, which doesn't matter at the
traffic volumes this deployment sees.
