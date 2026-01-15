#!/bin/bash

# Production startup script (used in Docker)
export PORT=${PORT:-8000}
export HOST=${HOST:-"0.0.0.0"}
export WORKERS=${WORKERS:-4}

echo "Starting API in production mode..."
uvicorn api.main:app --host $HOST --port $PORT --workers $WORKERS