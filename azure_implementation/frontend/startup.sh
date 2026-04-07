#!/bin/bash
# startup.sh — App Service startup command for InnovateTool
# Set this as the Startup Command in App Service → Configuration → General Settings

set -e

# Ensure the persistent DB directory exists (/home persists across restarts)
mkdir -p /home/innovate_tool

# Log startup info
echo "Starting InnovateTool..."
echo "DB_PATH: ${DB_PATH:-/home/innovate_tool/user.db}"
echo "AZURE_OPENAI_ENDPOINT: ${AZURE_OPENAI_ENDPOINT:-not set}"
echo "ADMIN_USERS: ${ADMIN_USERS:-not set}"

# Run from backend directory so relative imports work
cd /home/site/wwwroot/backend

exec gunicorn app:app \
  --workers 2 \
  --worker-class uvicorn.workers.UvicornWorker \
  --timeout 300 \
  --keep-alive 120 \
  --bind 0.0.0.0:8000 \
  --access-logfile - \
  --error-logfile - \
  --log-level info
