# Ouroboros Student Profile Agent

Microservice for the **Ouroboros AI** scholarship discovery platform. The Student Profile Agent parses CV/transcript documents, extracts structured student data using LLM (OpenAI/Anthropic), and stores profiles in MySQL using raw SQL with a repository pattern.

## Architecture

```
┌────────────────────────┐
│   Orchestrator (8000)  │
│   (single entry-point) │
└───────────┬────────────┘
            │ X-Service-Token
            ▼
┌────────────────────────┐
│  Student Profile Agent │
│       (port 8001)      │
│                        │
│  POST /profiles/parse  │  ← accept document, extract profile
│  GET  /profiles/{id}   │  ← retrieve profile
│  GET  /profiles        │  ← list profiles
│  PATCH /profiles/{id}  │  ← update profile
│  POST /profiles/{id}/  │  ← gap analysis
│        gap-analysis    │
│  GET  /documents/{id}  │  ← document metadata
└───────────┬────────────┘
            │
     ┌──────┴──────┐
     │  MySQL 8.0  │
     │  (raw SQL)  │
     └─────────────┘
```

## Key Design Decisions

- **No direct frontend access** — only the orchestrator calls this service via `X-Service-Token`
- **No SQLAlchemy** — raw SQL with `aiomysql` connection pool and repository pattern
- **LLM fallback** — OpenAI primary, Anthropic fallback with retry logic
- **Document parsing** — PDF (pdfplumber), DOCX (python-docx), OCR (pytesseract) for scanned docs

## Quick Start

```bash
# 1. Clone and setup
cp .env.example .env
# Edit .env with your database and API credentials

# 2. Create virtual environment
python -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements-dev.txt

# 4. Start MySQL (Docker)
docker compose up mysql -d

# 5. Run migrations
python scripts/run_migrations.py

# 6. Seed test data (optional)
python scripts/seed_test_data.py

# 7. Start the service
./start.sh
# or: uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

## Docker

```bash
docker compose up --build
```

## Testing

```bash
# Unit tests
ALLOW_DB_FAILURE=true X_SERVICE_TOKEN=test pytest tests/unit/ -v

# All tests with coverage
ALLOW_DB_FAILURE=true X_SERVICE_TOKEN=test pytest tests/ --cov=app -v
```

## Project Structure

```
app/
├── api/            # Route handlers (thin layer)
├── core/           # Logging, security
├── llm/            # LLM clients, prompts, schemas
├── middleware/      # Service auth, request logging
├── models/         # Pydantic request/response schemas
├── repositories/   # Raw SQL data access (aiomysql)
├── services/       # Business logic orchestration
└── utils/          # Helpers, exceptions, trace ID
migrations/         # SQL migration files
system_prompts/     # Version-controlled LLM prompts
tests/              # Unit and integration tests
```

## CI/CD

The pipeline (`.github/workflows/deploy.yml`) runs on PRs to `main`/`develop`:

1. **Format** — Black + isort
2. **Lint** — flake8 + pylint
3. **Unit Tests** — pytest
4. **Type Check** — mypy
5. **Integration Tests** — pytest with coverage
6. **Security Scan** — Bandit
7. **Docker Build** — verify image builds
