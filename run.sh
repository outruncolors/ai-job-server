#!/usr/bin/env bash
set -e

PIDS=$(lsof -ti :8090 2>/dev/null) || true
if [ -n "$PIDS" ]; then
  echo "Stopping process(es) on port 8090: $PIDS"
  kill -9 $PIDS 2>/dev/null || true
  while lsof -ti :8090 >/dev/null 2>&1; do sleep 0.2; done
fi

exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090
