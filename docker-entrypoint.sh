#!/bin/bash
set -e

DB_MAX_RETRIES="${DB_MAX_RETRIES:-30}"
DB_RETRY_INTERVAL_SECONDS="${DB_RETRY_INTERVAL_SECONDS:-2}"

echo "Starting container: waiting for database and running migrations..."
for ((i=1; i<=DB_MAX_RETRIES; i++)); do
    if uv run python scripts/run_migrations.py; then
        echo "Database is ready and migrations completed."
        exec uv run python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
    fi

    echo "Database not ready yet (attempt ${i}/${DB_MAX_RETRIES}). Retrying in ${DB_RETRY_INTERVAL_SECONDS}s..."
    sleep "${DB_RETRY_INTERVAL_SECONDS}"
done

echo "Database did not become ready after ${DB_MAX_RETRIES} attempts. Exiting."
exit 1
