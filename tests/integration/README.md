# Integration Testing

This directory contains integration tests that validate the application against a **real MySQL database**.

## Overview

Unlike unit tests (which use mocks), integration tests:

- Connect to a real MySQL instance
- Run actual database migrations
- Verify data persistence
- Test end-to-end API flows

## Local Integration Testing

### Prerequisites

- Docker and Docker Compose installed
- Python 3.11+ with virtual environment activated
- Dependencies installed (`uv sync --extra dev`)

### Running Integration Tests Locally

**Option 1: Automated Script (Recommended)**

```bash
./run-integration-tests.sh
```

This script:

1. Starts/reuses MySQL from the main `docker-compose.yml`
2. Waits for MySQL to be healthy
3. Runs all database migrations
4. Executes integration tests
5. Drops `student_profile_integration` and keeps MySQL running (shared dev container)

**Option 2: Manual Steps**

```bash
# Start/reuse shared MySQL service from main compose
export DB_PASSWORD='root_password'
docker-compose up -d mysql

# Wait for MySQL to be healthy
sleep 10

# Run migrations
export MYSQL_HOST='localhost'
export MYSQL_DATABASE='student_profile_integration'
export MYSQL_USER='root'
export MYSQL_PASSWORD='root_password'
export MYSQL_PORT='3308'

uv run python scripts/run_migrations.py

# Run integration tests
export ALLOW_DB_FAILURE='false'
export USE_MOCK_DATA='false'
uv run pytest tests/integration/ -v

# Optional cleanup (only if you want to stop shared MySQL)
docker-compose stop mysql
```

### Running Pytest Directly (Important)

When invoking integration tests directly (without `run-integration-tests.sh`), pass the integration env overrides inline so app startup does not inherit mock-friendly defaults from shared test setup.

```bash
ALLOW_DB_FAILURE=false USE_MOCK_DATA=false X_SERVICE_TOKEN=test-service-token \
    ./.venv/bin/python -m pytest -q tests/integration
```

This ensures FastAPI startup initializes the real DB pool instead of skipping DB with `ALLOW_DB_FAILURE=true`.

## CI/CD Integration

The GitHub Actions workflow automatically runs integration tests on every PR:

1. **Coverage Tests Job** — Runs unit + flow tests with mocked database (fast feedback)
2. **Integration Tests Job** — Runs actual integration tests with real MySQL service

### CI Test Database Configuration

The CI environment uses GitHub Actions' MySQL service:

- **Host**: `localhost`
- **Port**: `3308`
- **Database**: `student_profile_integration`
- **User**: `root`
- **Password**: `integration_password`

The workflow automatically:

- Starts the MySQL service
- Waits for it to be healthy
- Runs migrations
- Executes integration tests
- Archives results as artifacts

## Test Structure

```
tests/integration/
├── conftest.py              # Pytest fixtures for integration testing
├── __init__.py              # Package marker
└── test_profile_crud_integration.py  # Profile CRUD tests
```

### Integration Test Fixtures

**`conftest.py`** provides:

- `integration_client` — FastAPI TestClient with app
- `service_token_header` — Service authentication header
- `setup_integration_db` — Auto-runs migrations (session-scoped)
- `cleanup_integration_db` — Truncates tables after each test

## Test Examples

### Seed Profile + API Verification

```python
def test_parse_document_and_create_profile(
    integration_client, cleanup_integration_db, service_token_header
):
    profile_id = _seed_profile("John Doe", "john@example.com", 3.8)

    response = integration_client.get(
        f"/api/v1/profiles/{profile_id}",
        headers=service_token_header,
    )

    assert response.status_code == 200
```

## Database Cleanup

Each test:

1. Runs with a clean database (fixtures truncate tables before/after)
2. Has its own isolated transaction scope
3. Cleans up all side effects

Tables are truncated in reverse dependency order:

- `llm_call_logs`
- `gap_analysis_jobs`
- `gap_analysis`
- `experience_entries`
- `education_entries`
- `extracted_skills`
- `profile_versions`
- `documents`
- `student_profiles`

## Environment Variables

### Local Integration

```bash
ALLOW_DB_FAILURE=false
USE_MOCK_DATA=false
X_SERVICE_TOKEN=integration-service-token
MYSQL_HOST=localhost
MYSQL_PORT=3308
MYSQL_DATABASE=student_profile_integration
MYSQL_USER=root
MYSQL_PASSWORD=root_password
```

### CI Integration

Uses GitHub Actions MySQL service with the CI job values (for example `MYSQL_PASSWORD=integration_password`).

## Debugging

### MySQL Connection Issues

```bash
# Check if MySQL container is running
docker ps

# Check MySQL logs
docker-compose logs mysql

# Connect directly to verify
mysql -h localhost -P 3308 -u root -proot_password \
  -D student_profile_integration
```

### Test Failures

Run with increased verbosity:

```bash
uv run pytest tests/integration/ -vv --tb=long
```

Keep containers running for inspection:

```bash
docker-compose up mysql
# In another terminal
uv run pytest tests/integration/ -vv
# Containers stay up for debugging
```

## Adding New Integration Tests

1. Create test file in `tests/integration/`
2. Seed required rows directly in integration DB (keep tests deterministic)
3. Inject fixtures: `integration_client`, `cleanup_integration_db`, `service_token_header`
4. Use actual API endpoints (not mocks)
5. Verify database persistence, not just in-memory state

```python
def test_new_feature(integration_client, cleanup_integration_db, service_token_header):
    # Your test here
    pass
```

## Differences from Unit Tests

| Aspect    | Unit Tests                   | Integration Tests                |
| --------- | ---------------------------- | -------------------------------- |
| Database  | Mocked (FakeRepository)      | Real MySQL                       |
| Speed     | Fast (<1s each)              | Slower (3-5s each per DB ops)    |
| CI Mode   | `USE_MOCK_DATA=true`         | `USE_MOCK_DATA=false`            |
| Location  | `tests/unit/`, `tests/flow/` | `tests/integration/`             |
| Isolation | In-memory, no cleanup needed | Table truncation after each test |

## CI/CD Pipeline Flow

```
PR submitted
    ↓
[Parallel jobs]
├─ format + lint (fast)
├─ unit-tests (fast, mocked)
├─ type-check (medium)
├─ coverage-tests (medium, mocked + flow tests)
└─ integration-tests (longer, real MySQL)
    ↓
All pass → build-docker
    ↓
summary (report status)
```
