#!/bin/bash
set -e
cd "$(dirname "$0")"
echo "=============================================="
echo "AI Influencer Media Grabber - Startup Script"
echo "=============================================="

if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv .venv
fi

echo "Activating virtual environment..."
source .venv/bin/activate

if [ ! -f .venv/.core-ready ]; then
    python -m pip install -r requirements.txt
    touch .venv/.core-ready
fi

while true; do
    echo "Starting Flask server..."
    EXIT_CODE=0
    python app_local.py || EXIT_CODE=$?
    if [ $EXIT_CODE -eq 42 ]; then
        echo "Restart code received. Restarting..."
        sleep 1
    else
        echo "Server exited with code $EXIT_CODE."
        break
    fi
done
