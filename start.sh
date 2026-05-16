#!/bin/bash
set -e

echo "=== 简历优化分析平台 ==="
echo "Starting backend API (port 5002)..."
python backend_api.py &
BACKEND_PID=$!
sleep 2

echo "Starting frontend (port 5001)..."
python app.py &
FRONTEND_PID=$!

echo ""
echo "Backend  API: http://0.0.0.0:5002"
echo "Frontend UI: http://0.0.0.0:5001"
echo ""

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM
wait
