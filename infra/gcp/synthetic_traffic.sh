#!/bin/bash
set -uo pipefail

ENV_FILE="$HOME/ai-platform-builder/.env"
LOG_FILE="$HOME/synthetic_traffic.log"
POLL_INTERVAL_SECONDS=5
# Worst case is MAX_ATTEMPTS(2) x OLLAMA_TIMEOUT_SECONDS(220) = 440s if the
# first attempt runs the full timeout before the retry succeeds. Poll window
# needs real headroom above that or a slow-but-successful request gets
# misclassified as a timeout by this script when the pipeline actually
# delivered a result a bit later. Learned this the hard way on 2026-07-24.
POLL_TIMEOUT_SECONDS=480

if [ -f "$ENV_FILE" ]; then
  export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

MESSAGES=(
  "What happens when a Kafka consumer fails repeatedly?"
  "Summarize the retry and circuit breaker behavior of this platform."
  "Describe how requests are enriched with context before generation."
  "What does the dead letter queue do?"
  "Explain tenant isolation in this system."
  "What is the fallback behavior when the LLM provider is unavailable?"
)
MSG="${MESSAGES[$RANDOM % ${#MESSAGES[@]}]}"

log() {
  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  echo "[$ts] $1" >> "$LOG_FILE"
}

START=$(date +%s.%N)
RESP=$(curl -s -w '\n%{http_code}' -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -H "x-api-key: ${AI_PLATFORM_API_KEY}" \
  -d "{\"tenant_id\":\"synthetic-monitor\",\"message\":\"${MSG}\"}")

HTTP_CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | sed '$d')

if [ "$HTTP_CODE" != "200" ]; then
  log "outcome=accept_failed accept_status=$HTTP_CODE body=$BODY"
  exit 0
fi

REQUEST_ID=$(echo "$BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('request_id',''))" 2>/dev/null)
if [ -z "$REQUEST_ID" ]; then
  log "outcome=no_request_id accept_status=$HTTP_CODE body=$BODY"
  exit 0
fi

elapsed_poll=0
outcome="timeout"
while [ "$elapsed_poll" -lt "$POLL_TIMEOUT_SECONDS" ]; do
  sleep "$POLL_INTERVAL_SECONDS"
  elapsed_poll=$((elapsed_poll + POLL_INTERVAL_SECONDS))
  RESULT=$(curl -s "http://localhost:8000/chat/${REQUEST_ID}" -H "x-api-key: ${AI_PLATFORM_API_KEY}")
  STATUS=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
    outcome="$STATUS"
    break
  fi
done

END=$(date +%s.%N)
total_elapsed=$(echo "$END - $START" | bc)

log "request_id=$REQUEST_ID accept_status=$HTTP_CODE outcome=$outcome poll_elapsed=${elapsed_poll}s total_elapsed=${total_elapsed}s"
