#!/usr/bin/env bash
# Azure App Service (Linux, Python) startup command.
# Configure in Web App → Configuration → General settings → Startup Command:
#   bash startup.sh
set -euo pipefail

exec gunicorn \
    -k uvicorn.workers.UvicornWorker \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --bind "0.0.0.0:${PORT:-8000}" \
    --access-logfile - \
    --error-logfile - \
    'main:app'
