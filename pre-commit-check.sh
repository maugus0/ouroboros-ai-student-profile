#!/bin/bash
# Pre-commit check script for Student Profile Agent
set -e

echo "Running pre-commit checks..."
echo ""

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

success() { echo -e "${GREEN}  $1${NC}"; }
error()   { echo -e "${RED}  $1${NC}"; }
warning() { echo -e "${YELLOW}  $1${NC}"; }

VENV_ACTIVATED=false
for VENV_DIR in ".venv" "venv" "env"; do
    if [ -d "${VENV_DIR}" ] && [ -f "${VENV_DIR}/bin/activate" ]; then
        source "${VENV_DIR}/bin/activate"
        VENV_ACTIVATED=true
        break
    fi
done

if [ "${VENV_ACTIVATED}" = true ]; then
    success "Using Python virtual environment"
else
    warning "Proceeding without venv"
fi

if ! command -v uv > /dev/null 2>&1; then
    error "uv is required but not found. Install with: pip install uv"
    exit 1
fi

PYTHON_CMD="python"
if ! command -v "${PYTHON_CMD}" > /dev/null 2>&1; then
    if command -v python3 > /dev/null 2>&1; then
        PYTHON_CMD="python3"
    else
        error "Python interpreter not found."
        exit 1
    fi
fi

echo "1. Checking code formatting (Black)..."
if uv run black --check app/ tests/ > /dev/null 2>&1; then
    success "Code formatting passed"
else
    error "Formatting failed. Run: uv run black app/ tests/"
    exit 1
fi

echo ""
echo "2. Checking import sorting (isort)..."
if uv run isort --check-only app/ tests/ > /dev/null 2>&1; then
    success "Import sorting passed"
else
    error "Import sorting failed. Run: uv run isort app/ tests/"
    exit 1
fi

echo ""
echo "3. Running linting (flake8)..."
if uv run flake8 app/ tests/ --max-line-length=120 --extend-ignore=E203,W503,E501 > /dev/null 2>&1; then
    success "Linting passed (flake8)"
else
    error "Linting failed (flake8)"
    exit 1
fi

echo ""
echo "4. Running pylint..."
if uv run pylint app/ tests/ --disable=R0911,R0912,R0913,R0914,R0915,R0917,W0613 > /dev/null 2>&1; then
    success "Linting passed (pylint)"
else
    error "Linting failed (pylint)"
    uv run pylint app/ tests/ --disable=R0911,R0912,R0913,R0914,R0915,R0917,W0613
    exit 1
fi

echo ""
echo "5. Validating Python syntax..."
if "${PYTHON_CMD}" -m py_compile app/main.py app/config.py > /dev/null 2>&1; then
    success "Syntax validation passed"
else
    error "Syntax validation failed"
    exit 1
fi

echo ""
echo "6. Running tests..."
TEST_TARGETS="tests/unit tests/flow"
if [ "${RUN_INTEGRATION_TESTS:-false}" = "true" ]; then
    TEST_TARGETS="${TEST_TARGETS} tests/integration"
fi

if ALLOW_DB_FAILURE=true USE_MOCK_DATA=true X_SERVICE_TOKEN=test-service-token MYSQL_HOST=localhost MYSQL_DATABASE=test_db MYSQL_USER=test_user MYSQL_PASSWORD=test_pass uv run pytest ${TEST_TARGETS} -v --tb=short > /dev/null 2>&1; then
    success "Tests passed"
else
    error "Tests failed"
    ALLOW_DB_FAILURE=true USE_MOCK_DATA=true X_SERVICE_TOKEN=test-service-token MYSQL_HOST=localhost MYSQL_DATABASE=test_db MYSQL_USER=test_user MYSQL_PASSWORD=test_pass uv run pytest ${TEST_TARGETS} -v --tb=short
    exit 1
fi

echo ""
echo "7. Running type checking (mypy)..."
if uv run mypy app/ --ignore-missing-imports --no-strict-optional > /dev/null 2>&1; then
    success "Type checking passed"
else
    error "Type checking failed (mypy)"
    uv run mypy app/ --ignore-missing-imports --no-strict-optional
    exit 1
fi

echo ""
echo -e "${GREEN}All checks passed! Ready to commit.${NC}"
