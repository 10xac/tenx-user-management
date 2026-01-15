#!/bin/bash

# Local development script (no Docker)
# Usage: ./dev.sh

export PORT=${PORT:-8123}
export HOST=${HOST:-"127.0.0.1"}

echo "Starting API in development mode with hot reload..."
uvicorn api.main:app --reload --host $HOST --port $PORT
