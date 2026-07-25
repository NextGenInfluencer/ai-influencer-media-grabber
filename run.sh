#!/bin/bash
echo "=============================================="
echo "AI Influencer Media Grabber - Startup Script"
echo "=============================================="

if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv .venv
fi

echo "Activating virtual environment..."
source .venv/bin/activate

echo "Installing dependencies..."
pip install -q -r requirements.txt

echo "Starting Flask server..."
python app_local.py
