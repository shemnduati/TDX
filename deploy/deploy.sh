#!/usr/bin/env bash
# Run on the production host after 'git reset --hard origin/main' in /opt/tdx.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/tdx}"
cd "$APP_DIR"

echo "==> Python dependencies"
./venv/bin/pip install --upgrade pip
# Python 3.14: coincurve may fail to build; ccxt works without it for public OHLCV.
if ./venv/bin/python -c 'import sys; exit(0 if sys.version_info >= (3, 14) else 1)' 2>/dev/null; then
  grep -v '^coincurve' requirements.txt | ./venv/bin/pip install -r /dev/stdin
else
  ./venv/bin/pip install -r requirements.txt
fi

echo "==> Frontend build"
cd frontend
npm ci
npm run build
cd "$APP_DIR"

echo "==> Restart API"
systemctl restart tdx-api
sleep 2
curl -sf http://127.0.0.1:5001/health >/dev/null
echo "Deploy OK — $(git rev-parse --short HEAD)"
