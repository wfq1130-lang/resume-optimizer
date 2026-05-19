#!/bin/bash
set -e

BACKEND_PORT=${BACKEND_PORT:-5002}
FRONTEND_PORT=${PORT:-5001}

echo "=== 简历优化分析平台 ==="
echo "PORT env: $FRONTEND_PORT"
echo "Starting backend API (port $BACKEND_PORT)..."
python backend_api.py &
BACKEND_PID=$!

# Health check backend
for i in $(seq 1 30); do
  sleep 1
  if curl -sf http://127.0.0.1:${BACKEND_PORT}/health > /dev/null 2>&1; then
    echo "Backend healthy after ${i}s"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "ERROR: Backend failed to start on port $BACKEND_PORT"
    kill $BACKEND_PID 2>/dev/null
    exit 1
  fi
done

echo "Starting frontend (port $FRONTEND_PORT)..."
python app.py &
FRONTEND_PID=$!

# Health check frontend
for i in $(seq 1 30); do
  sleep 1
  if curl -sf http://127.0.0.1:${FRONTEND_PORT}/health > /dev/null 2>&1; then
    echo "Frontend healthy after ${i}s"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "ERROR: Frontend failed to start on port $FRONTEND_PORT"
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    exit 1
  fi
done

echo ""
echo "Backend  API: http://0.0.0.0:$BACKEND_PORT"
echo "Frontend UI: http://0.0.0.0:$FRONTEND_PORT"
echo ""

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM
wait
