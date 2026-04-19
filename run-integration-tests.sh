#!/bin/bash
# Script to run integration tests locally against the existing MySQL container
set -e

echo "=========================================="
echo "Integration Test Runner (Shared MySQL Container)"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

success() { echo -e "${GREEN}✓ $1${NC}"; }
error() { echo -e "${RED}✗ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠ $1${NC}"; }

if ! command -v uv > /dev/null 2>&1; then
    error "uv is required but not found. Install with: pip install uv"
    exit 1
fi

# Cleanup function
cleanup() {
    # Best-effort cleanup: remove integration test database but keep shared MySQL container running
    if docker-compose exec -T mysql sh -c "exit 0" > /dev/null 2>&1; then
        if docker-compose exec -T -e MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql \
            mysql -uroot \
            -e "DROP DATABASE IF EXISTS student_profile_integration;" > /dev/null 2>&1; then
            success "Integration database removed"
        else
            warning "Could not drop integration database automatically"
        fi
    fi

    exit "$1"
}

trap "cleanup 1" INT TERM

# Check if Docker is running
if ! docker ps > /dev/null 2>&1; then
    error "Docker is not running. Please start Docker and try again."
    exit 1
fi

success "Docker is running"

# Start/reuse MySQL service from main docker-compose
echo ""
echo "1. Starting or reusing MySQL container for integration tests..."
export DB_PASSWORD="${DB_PASSWORD:-Admin123!}"
export DOCKER_MYSQL_PORT=3308
MYSQL_ROOT_PASSWORD="${DB_PASSWORD}"

docker-compose up -d mysql
success "MySQL service is ready to be used"

# Wait for MySQL to be healthy
echo ""
echo "2. Waiting for MySQL to be healthy..."
COUNTER=0
MAX_ATTEMPTS=30

while [ $COUNTER -lt $MAX_ATTEMPTS ]; do
    if docker-compose exec -T mysql mysqladmin ping -h localhost > /dev/null 2>&1; then
        success "MySQL is healthy"
        break
    fi
    COUNTER=$((COUNTER + 1))
    echo "  Attempt $COUNTER/$MAX_ATTEMPTS..."
    sleep 2
done

if [ $COUNTER -eq $MAX_ATTEMPTS ]; then
    error "MySQL failed to become healthy"
    cleanup 1
fi

# Ensure integration database exists in the same MySQL instance
echo ""
echo "3. Creating integration database if needed..."
docker-compose exec -T -e MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql \
    mysql -uroot \
    -e "CREATE DATABASE IF NOT EXISTS student_profile_integration CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
success "Integration database ready"

# Run migrations
echo ""
echo "4. Running database migrations..."
export MYSQL_HOST='localhost'
export MYSQL_DATABASE='student_profile_integration'
export MYSQL_USER='root'
export MYSQL_PASSWORD="${MYSQL_ROOT_PASSWORD}"
export MYSQL_PORT='3308'

if uv run python scripts/run_migrations.py; then
    success "Migrations completed"
else
    error "Migrations failed"
    cleanup 1
fi

# Run integration tests
echo ""
echo "5. Running integration tests..."
export ALLOW_DB_FAILURE='false'
export USE_MOCK_DATA='false'
export X_SERVICE_TOKEN='integration-service-token'

if uv run pytest tests/integration/ -v --tb=short; then
    success "Integration tests passed"
    CLEANUP_CODE=0
else
    error "Integration tests failed"
    CLEANUP_CODE=1
fi

cleanup "$CLEANUP_CODE"
