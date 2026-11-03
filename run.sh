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

# Re-sync core packages whenever requirements.txt changes (hash stamp, not a one-time marker).
REQ_STAMP=.venv/.core-requirements.sha256
REQ_HASH=$(python -c "import hashlib; print(hashlib.sha256(open('requirements.txt', 'rb').read()).hexdigest())")
OLD_HASH=""
[ -f "$REQ_STAMP" ] && OLD_HASH=$(cat "$REQ_STAMP")
if [ "$REQ_HASH" != "$OLD_HASH" ]; then
    echo "Syncing core dependencies with requirements.txt..."
    if python -m pip install -r requirements.txt; then
        echo "$REQ_HASH" > "$REQ_STAMP"
        rm -f .venv/.core-ready
    elif [ -n "$OLD_HASH" ] || [ -f .venv/.core-ready ]; then
        echo "[WARNING] Core dependencies could not be updated. Starting with the installed packages."
    else
        exit 1
    fi
fi

echo "Starting Flask server..."
# The in-app Restart button starts a fresh server process itself, so no restart loop is needed.
EXIT_CODE=0
python app_local.py || EXIT_CODE=$?
echo "Server process exited with code $EXIT_CODE."
