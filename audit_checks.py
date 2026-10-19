"""Run current regression checks. Historical audit evidence is in audit_artifacts/results.json."""
import subprocess
import sys
from pathlib import Path

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=Path(__file__).resolve().parent))
