#!/usr/bin/env bash
# Run scrape.py and load.py to completion. Restarts scrape on failure;
# the on-disk HTML cache makes restarts cheap (only un-cached or failed
# pages are re-fetched).

set -u
cd "$(dirname "$0")"

LOG=data/full-run.log
mkdir -p data

echo "=== full run started $(date -Iseconds) ===" | tee -a "$LOG"

attempt=0
max_attempts=10
while (( attempt < max_attempts )); do
  attempt=$(( attempt + 1 ))
  echo "--- scrape attempt $attempt at $(date -Iseconds) ---" | tee -a "$LOG"
  if .venv/bin/python -u scrape.py \
      --season-from 2000 --season-to 2024 \
      --workers 4 \
      >>"$LOG" 2>&1; then
    echo "--- scrape succeeded on attempt $attempt ---" | tee -a "$LOG"
    break
  fi
  echo "--- scrape failed (exit $?), sleeping 60s before retry ---" | tee -a "$LOG"
  sleep 60
done

if (( attempt >= max_attempts )); then
  echo "=== gave up after $max_attempts attempts ===" | tee -a "$LOG"
  exit 1
fi

echo "--- loading SQLite at $(date -Iseconds) ---" | tee -a "$LOG"
.venv/bin/python -u load.py >>"$LOG" 2>&1
echo "=== full run done $(date -Iseconds) ===" | tee -a "$LOG"
