#!/bin/bash
# start.sh

# Fail on error
set -e

# Print PORT to debug
echo "Starting Gunicorn on PORT: ${PORT:-8000}"

exec gunicorn -w 4 -k uvicorn.workers.UvicornWorker app:app -b 0.0.0.0:${PORT:-8000}
