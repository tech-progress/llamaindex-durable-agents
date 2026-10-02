#!/usr/bin/env sh
set -eu
exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-3000}" --workers 1 --timeout-graceful-shutdown 5 --no-access-log
