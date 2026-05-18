#!/bin/bash
set -e

echo "=== 简历优化分析平台 ==="
echo "Starting backend API (port 5002)..."
python backend_api.py &
BACKEND_PID=$!

# Health check backend
for i in $(seq 1 30); do
  sleep 1
  if curl -sf http://127.0.0.1:5002/health > /dev/null 2>&1; then
    echo "Backend healthy after ${i}s"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "ERROR: Backend failed to start"
    kill $BACKEND_PID 2>/dev/null
    exit 1
  fi
done

echo "Starting frontend (port 5001)..."
python app.py &
FRONTEND_PID=$!

# Health check frontend
for i in $(seq 1 30); do
  sleep 1
  if curl -sf http://127.0.0.1:5001/health > /dev/null 2>&1; then
    echo "Frontend healthy after ${i}s"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "ERROR: Frontend failed to start"
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    exit 1
  fi
done

echo ""
echo "Backend  API: http://0.0.0.0:5002"
echo "Frontend UI: http://0.0.0.0:5001"
echo ""

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM
wait
