#!/bin/sh
# Starts the Python API on this container's loopback and the web server on the public port.
# If either one stops, the container stops (so the host restarts it) instead of limping along half alive,
# and the log says which one stopped and how.
set -eu

if [ -z "${SKILLFORGE_ACCESS_TOKEN:-}" ]; then
  echo "SKILLFORGE_ACCESS_TOKEN is not set. Set it as a secret on the host: a long random string (at least 20 characters)." >&2
  exit 1
fi

export SKILLFORGE_MODE=hosted
PORT="${PORT:-8080}"

python -m skillforge serve --host 127.0.0.1 --port 8000 &
api=$!

HOSTNAME=0.0.0.0 PORT="$PORT" node /app/web/server.js &
web=$!

trap 'kill "$api" "$web" 2>/dev/null || true' INT TERM

while :; do
  if ! kill -0 "$api" 2>/dev/null; then
    code=0
    wait "$api" || code=$?
    echo "The API (Python) stopped with exit code $code, so the container is stopping." >&2
    break
  fi
  if ! kill -0 "$web" 2>/dev/null; then
    code=0
    wait "$web" || code=$?
    echo "The web server (Node) stopped with exit code $code, so the container is stopping." >&2
    break
  fi
  sleep 1
done
kill "$api" "$web" 2>/dev/null || true
exit 1
