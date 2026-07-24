#!/bin/bash
set -euo pipefail

SCRIPT="$HOME/scripts/synthetic_traffic.sh"
LOG_FILE="$HOME/scheduler.log"
REQUESTS_PER_DAY=8
WINDOW_MINUTES=$((24 * 60 / REQUESTS_PER_DAY))

TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "[$TS] scheduling $REQUESTS_PER_DAY runs for today" >> "$LOG_FILE"

for i in $(seq 0 $((REQUESTS_PER_DAY - 1))); do
  base_minute=$((i * WINDOW_MINUTES))
  offset=$((RANDOM % WINDOW_MINUTES))
  total_minute=$((base_minute + offset))
  hour=$((total_minute / 60))
  minute=$((total_minute % 60))
  at_time=$(printf "%02d:%02d" "$hour" "$minute")
  echo "$SCRIPT" | at "$at_time" >> "$LOG_FILE" 2>&1
done
