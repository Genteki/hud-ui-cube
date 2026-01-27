#!/bin/bash
set -e

# Start npm preview server (always needed for navigation tests)
echo "[entrypoint] Starting npm preview server..." >&2
cd /app/uipath_enterprise_benchmark/DeterministicBenchmark
npm run preview -- --host 0.0.0.0 --port 3000 </dev/null >&2 &
NPM_PID=$!

# Only start Xvfb if NOT running in headless mode
if [ "${PLAYWRIGHT_HEADLESS:-1}" != "1" ]; then
    echo "[entrypoint] Starting Xvfb (PLAYWRIGHT_HEADLESS != 1)..." >&2
    # Use DISPLAY_WIDTH and DISPLAY_HEIGHT env vars (default to 1920x1080)
    WIDTH="${DISPLAY_WIDTH:-1920}"
    HEIGHT="${DISPLAY_HEIGHT:-1080}"
    Xvfb :1 -screen 0 ${WIDTH}x${HEIGHT}x24 &
    export DISPLAY=:1
    sleep 1
else
    echo "[entrypoint] Headless mode - skipping Xvfb" >&2
fi

# Wait for npm server to be ready
echo "[entrypoint] Waiting for preview server to start..." >&2
sleep 3

# Check if npm is still running
if ! kill -0 $NPM_PID 2>/dev/null; then
    echo "[entrypoint] ERROR: npm preview server failed to start" >&2
    exit 1
fi

echo "[entrypoint] Starting MCP server..." >&2
exec python3 -u /app/env.py
