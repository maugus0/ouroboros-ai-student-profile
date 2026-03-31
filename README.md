# Ouroboros Student Profile Agent

Microservice for the **Ouroboros AI** scholarship discovery platform. The Student Profile Agent parses CV/transcript documents, extracts structured student data using LLM (OpenAI/Anthropic with intelligent fallback), and stores profiles in MySQL using raw SQL with a repository pattern.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Database Schema](#database-schema)
- [API Endpoints](#api-endpoints)
- [Prompt System](#prompt-system)
- [Development Workflow](#development-workflow)
- [Testing](#testing)
- [CI/CD Pipeline](#cicd-pipeline)
- [Deployment](#deployment)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Attribution](#attribution)

---

## Overview

The Student Profile Agent is a critical microservice in the Ouroboros AI platform that:

1. **Accepts document uploads** (CV, transcripts) from the orchestrator service
2. **Extracts text** from multiple formats (PDF, DOCX, scanned images via OCR)
3. **Leverages LLM** to parse unstructured academic documents into structured JSON profiles
4. **Identifies gaps** in student qualifications against degree-level baselines
5. **Stores profiles** in MySQL with full audit trails and confidence metadata

**Key Design Principles:**

- No direct frontend access — only the orchestrator calls this service via `X-Service-Token`
- No ORM overhead — raw SQL with `aiomysql` async connection pool
- LLM resilience — OpenAI primary, Anthropic fallback with retry logic
- Confidence tracking — every extracted field includes evidence and confidence scores
- JSON prompt templates — version-controlled in `prompts/` with runtime context injection

---

## Architecture

```
┌─────────────────────────────────────┐
│    Orchestrator Service (8000)      │
│    (Single Entry Point)             │
└──────────────┬──────────────────────┘
               │
               │ X-Service-Token
               ▼
┌──────────────────────────────────────────────────────┐
│         Student Profile Agent (8001)                 │
│                                                      │
│  ┌─────────────────────────────────────────────┐     │
│  │  API Layer (FastAPI)                        │     │
│  │  POST /api/v1/profiles/parse                │     │
│  │  POST /api/v1/profiles/parse-upload         │     │
│  │  GET  /api/v1/profiles/{profile_id}         │     │
│  │  GET  /api/v1/profiles (paginated)          │     │
│  │  PUT  /api/v1/profiles/{profile_id}         │     │
│  │  GET  /api/v1/profiles/{profile_id}/skills  │     │
│  │  GET  /api/v1/profiles/{profile_id}/gaps    │     │
│  │  POST /api/v1/profiles/{profile_id}/gap-analysis │  │
│  │  GET  /documents/{id}                       │     │
│  └─────────────────────┬───────────────────────┘     │
│                        │                             │
│  ┌─────────────────────▼───────────────────────┐     │
│  │  Service Layer                              │     │
│  │  ProfileService (parse -> extract -> store) │     │
│  │  DocumentParser  (PDF / DOCX / OCR)         │     │
│  │  LLMService      (OpenAI -> Anthropic)      │     │
│  │  GapAnalysisService                         │     │
│  └─────────────────────┬───────────────────────┘     │
│                        │                             │
│  ┌─────────────────────▼───────────────────────┐     │
│  │  Repository Layer (Raw SQL)                 │     │
│  │  ProfileRepository                          │     │
│  │  DocumentRepository                         │     │
│  │  ProfileNormalizedRepository                │     │
│  └─────────────────────────────────────────────┘     │
└──────────────┬───────────────────────────────────────┘
               │
               ▼
      ┌─────────────────┐
      │   MySQL 8.0     │
      │   (aiomysql)    │
      └─────────────────┘
```

---

## Features

### Document Processing

- **PDF extraction** via `pdfplumber` (handles tables, multi-column layouts)
- **DOCX extraction** via `python-docx`
- **OCR fallback** via `pytesseract` for scanned/image-based documents
- **File validation** (extension, size limits, MIME type detection)
- **Deduplication** via SHA-256 file hashing

### LLM Integration

- **Primary provider**: OpenAI (`gpt-4o-mini` default, configurable)
- **Fallback provider**: Anthropic (`claude-sonnet-4` default, configurable)
- **Retry logic** via `tenacity` (exponential backoff)
- **Structured output** validation via Pydantic schemas
- **Context injection** — runtime metadata merged into JSON prompt templates
- **Prompt versioning** — JSON templates in `prompts/` directory

### Profile Extraction

- **Personal data**: Name, email, phone, nationality, DOB
- **Academic history**: Education entries with GPA/scale/achievements
- **Target degree detection**: Inference with confidence scoring
- **Clarification workflow**: Deterministic checks generate a clarification queue for unresolved critical fields
- **Decision trace**: ReAct-style `react_decision_trace` captures accept/clarify reasoning per critical field
- **Work experience**: Company, role, dates, skills used
- **Research experience**: Publications, projects, venues
- **Skills taxonomy**: Technical skills, languages, certifications
- **Confidence metadata**: Per-field confidence scores (0.0-1.0)
- **Evidence tracking**: Source snippets for every extracted field
- **Contradiction detection**: Flags conflicts between CV and transcript

### Gap Analysis

- **Baseline templates**: Bachelor/Master/PhD requirement expectations
- **Readiness scoring**: Weighted average across required areas
- **Gap identification**: Missing/weak signals with severity levels
- **Actionable recommendations**: Prioritised improvement suggestions

---

## Prerequisites

| Tool              | Version | Purpose                                          |
| ----------------- | ------- | ------------------------------------------------ |
| Python            | 3.11+   | Runtime                                          |
| MySQL             | 8.0+    | Database                                         |
| OpenAI API Key    | —       | Primary LLM provider                             |
| Anthropic API Key | —       | Fallback LLM provider (optional but recommended) |
| Tesseract OCR     | 4.0+    | Scanned document processing (optional)           |
| Docker            | 24.0+   | Containerised deployment (optional)              |

---

## Quick Start

### 1. Clone and Setup

```bash
git clone https://github.com/maugus0/ouroboros-ai-student-profile.git
cd ouroboros-ai-student-profile

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
uv sync --extra dev
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
DB_HOST=localhost
DB_NAME=student_profile_db
DB_USERNAME=root
DB_PASSWORD=your_mysql_password

X_SERVICE_TOKEN=your-secret-service-token-change-this

OPENAI_API_KEY=sk-your-openai-key-here
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key-here
```

See [Configuration](#configuration) for the full reference.

### 3. Database Setup

**Option A: Docker (Recommended)**

```bash
docker compose up mysql -d
docker compose logs -f mysql   # wait for "ready for connections"
```

**Option B: Local MySQL**

```bash
mysql -u root -p -e "CREATE DATABASE student_profile_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### 4. Run Migrations

```bash
python scripts/run_migrations.py
```

Expected output:

```
Running migration: 001_create_student_profiles.sql
  ✓ 001_create_student_profiles.sql applied
Running migration: 002_create_documents.sql
  ✓ 002_create_documents.sql applied
...
All migrations applied successfully.
```

### 5. Seed Test Data (Optional)

```bash
python scripts/seed_test_data.py
```

### 6. Start the Service

```bash
./start.sh
# or: uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

### 7. Verify Health

```bash
curl http://localhost:8001/health
# {"status":"healthy","version":"0.1.0","database":"connected"}
```

If the database is unavailable, health returns degraded state:

```json
{ "status": "degraded", "version": "0.1.0", "database": "not_connected" }
```

Swagger docs are available at `http://localhost:8001/docs`.

---

## Configuration

### Environment Variables

| Variable                | Required    | Default                    | Description                                         |
| ----------------------- | ----------- | -------------------------- | --------------------------------------------------- |
| **Database**            |             |                            |                                                     |
| `DB_HOST`               | No          | `localhost`                | MySQL host                                          |
| `DB_PORT`               | No          | `3306`                     | MySQL port                                          |
| `DB_NAME`               | No          | `student_profile_db`       | Database name                                       |
| `DB_USERNAME`           | No          | `root`                     | MySQL user                                          |
| `DB_PASSWORD`           | Yes         | —                          | MySQL password                                      |
| `DB_POOL_SIZE`          | No          | `10`                       | Max connections in pool                             |
| **Service Auth**        |             |                            |                                                     |
| `X_SERVICE_TOKEN`       | Yes         | —                          | Inter-service auth token (shared with orchestrator) |
| **LLM — OpenAI**        |             |                            |                                                     |
| `OPENAI_API_KEY`        | Yes         | —                          | OpenAI API key                                      |
| `OPENAI_MODEL`          | No          | `gpt-4o-mini`              | Model identifier                                    |
| `OPENAI_MAX_TOKENS`     | No          | `2000`                     | Max output tokens                                   |
| `OPENAI_TEMPERATURE`    | No          | `0.0`                      | Sampling temperature                                |
| **LLM — Anthropic**     |             |                            |                                                     |
| `ANTHROPIC_API_KEY`     | Recommended | —                          | Anthropic API key (fallback)                        |
| `ANTHROPIC_MODEL`       | No          | `claude-sonnet-4-20250514` | Model identifier                                    |
| `ANTHROPIC_MAX_TOKENS`  | No          | `2000`                     | Max output tokens                                   |
| `LLM_MAX_RETRIES`       | No          | `3`                        | Max retries per provider call                       |
| `LLM_RETRY_DELAY`       | No          | `2`                        | Retry delay (seconds)                               |
| **Document Processing** |             |                            |                                                     |
| `MAX_FILE_SIZE_MB`      | No          | `10`                       | Max upload size                                     |
| `ALLOWED_EXTENSIONS`    | No          | `.pdf,.docx`               | Comma-separated                                     |
| `TEMP_UPLOAD_DIR`       | No          | `/tmp/uploads`             | Temp file directory                                 |
| `TESSERACT_PATH`        | No          | auto-detect                | Tesseract executable path                           |
| `OCR_LANGUAGE`          | No          | `eng`                      | Tesseract language code                             |
| **Application**         |             |                            |                                                     |
| `LOG_LEVEL`             | No          | `INFO`                     | `DEBUG\|INFO\|WARNING\|ERROR\|CRITICAL`             |
| `USE_MOCK_DATA`         | No          | `true`                     | Use in-memory repos (tests/dev convenience)         |
| `ALLOW_DB_FAILURE`      | No          | `false`                    | Continue if DB unavailable (tests only)             |
| **Docker Runtime**      |             |                            |                                                     |
| `RUN_STARTUP_SCRIPTS`   | No          | `true`                     | Toggle startup script execution in containers       |
| `DOCKER_MYSQL_PORT`     | No          | `3308`                     | Host port mapped to MySQL in docker compose         |

### Docker / CI Prefix Compatibility

The service also reads `MYSQL_*` variables for Docker/CI environments:

| `DB_*` Prefix | Equivalent `MYSQL_*` |
| ------------- | -------------------- |
| `DB_HOST`     | `MYSQL_HOST`         |
| `DB_NAME`     | `MYSQL_DATABASE`     |
| `DB_USERNAME` | `MYSQL_USER`         |
| `DB_PASSWORD` | `MYSQL_PASSWORD`     |
| `DB_PORT`     | `MYSQL_PORT`         |

Resolution logic lives in the `settings.get_db_*()` helpers in `app/config.py`.

---

## Database Schema

### Tables

| Table                | Purpose                                                                     |
| -------------------- | --------------------------------------------------------------------------- |
| `student_profiles`   | Lean scalar profile record (core identity, degree, and processing metadata) |
| `documents`          | Uploaded CV/transcript file metadata (hash, extraction method, OCR flag)    |
| `extracted_skills`   | Normalized skill rows for direct querying and deduplication                 |
| `education_entries`  | Normalized education history entries                                        |
| `experience_entries` | Normalized work/research experience entries                                 |
| `profile_versions`   | Full JSON profile snapshots per version (authoritative profile state)       |
| `gap_analysis`       | Readiness scan results with gap list and recommendations                    |
| `gap_analysis_jobs`  | Async job queue and execution state for gap analysis                        |
| `llm_call_logs`      | Audit trail — tokens, cost, latency, retries for every LLM call             |

### Relationships

```
student_profiles (1) ──< (N) documents
student_profiles (1) ──< (N) extracted_skills
student_profiles (1) ──< (N) education_entries
student_profiles (1) ──< (N) experience_entries
student_profiles (1) ──< (N) profile_versions
student_profiles (1) ──< (N) gap_analysis
student_profiles (1) ──< (N) gap_analysis_jobs
student_profiles (1) ──< (N) llm_call_logs
documents        (1) ──< (N) extracted_skills   [via source_document_id]
documents        (1) ──< (N) education_entries  [via source_document_id]
documents        (1) ──< (N) experience_entries [via source_document_id]
```

### Migrations

Run in order via `python scripts/run_migrations.py`:

```
migrations/
├── 001_create_student_profiles.sql
├── 002_create_documents.sql
├── 003_create_extracted_skills.sql
├── 004_create_education_entries.sql
├── 005_create_experience_entries.sql
├── 006_create_profile_versions.sql
├── 007_create_gap_analysis.sql
├── 008_create_gap_analysis_jobs.sql
└── 009_create_llm_call_logs.sql
```

---

## API Endpoints

**Base URL**: `http://localhost:8001`

All endpoints (except health) require the `X-Service-Token` header.

### Health

| Method | Path      | Auth | Description            |
| ------ | --------- | ---- | ---------------------- |
| GET    | `/`       | No   | Root health check      |
| GET    | `/health` | No   | Detailed health status |

### Profiles

| Method | Path                                              | Description                                                     |
| ------ | ------------------------------------------------- | --------------------------------------------------------------- |
| POST   | `/api/v1/profiles/parse`                          | Parse document and create profile (also runs auto gap analysis) |
| POST   | `/api/v1/profiles/parse-upload`                   | Parse streamed multipart upload and create profile              |
| GET    | `/api/v1/profiles/{profile_id}/clarifications`    | Get unresolved clarifications and readiness state               |
| POST   | `/api/v1/profiles/{profile_id}/clarifications`    | Submit clarification answers                                    |
| GET    | `/api/v1/profiles/{profile_id}`                   | Retrieve single profile                                         |
| GET    | `/api/v1/profiles`                                | List profiles (paginated: `?page=1&page_size=20`)               |
| PATCH  | `/api/v1/profiles/{profile_id}`                   | Partial update profile fields                                   |
| PUT    | `/api/v1/profiles/{profile_id}`                   | Update profile fields                                           |
| GET    | `/api/v1/profiles/{profile_id}/skills`            | Retrieve normalized skills list                                 |
| GET    | `/api/v1/profiles/{profile_id}/gaps`              | Retrieve latest gap analysis snapshot                           |
| POST   | `/api/v1/profiles/{profile_id}/gap-analysis`      | Run gap analysis                                                |
| POST   | `/api/v1/profiles/{profile_id}/gap-analysis/jobs` | Create async gap-analysis job                                   |
| GET    | `/api/v1/profiles/gap-analysis/jobs/{job_id}`     | Get async gap-analysis job status/result                        |

`POST /api/v1/profiles/{profile_id}/gap-analysis/jobs` behavior:

- Returns `queued` when the profile has no pending clarifications.
- Returns `blocked` with an error message when clarification is still required.

### Documents

| Method | Path                              | Description                  |
| ------ | --------------------------------- | ---------------------------- |
| GET    | `/documents/{id}`                 | Get document metadata        |
| GET    | `/documents/profile/{profile_id}` | List documents for a profile |

### Example: Parse a Document

```bash
curl -X POST http://localhost:8001/api/v1/profiles/parse \
  -H "X-Service-Token: your-service-token" \
  -H "Content-Type: application/json" \
  -d '{
    "document_type": "cv",
    "file_name": "cv.pdf",
    "file_content_base64": "JVBERi0xLjQK...",
    "target_degree_hint": "master"
  }'
```

Response:

```json
{
  "success": true,
  "message": "Profile created",
  "data": {
    "profile_id": "550e8400-e29b-41d4-a716-446655440000",
    "profile_data": {
      "full_name": "Jane Doe",
      "email": "jane@example.com",
      "...": "..."
    },
    "llm_provider": "openai",
    "llm_model": "gpt-4o-mini",
    "fallback_used": false,
    "total_processing_time_ms": 3420
  }
}
```

### Example: Parse a Streamed File Upload (Multipart)

Use this when you want to upload a file directly instead of sending base64 content.

```bash
curl -X POST http://localhost:8001/api/v1/profiles/parse-upload \
  -H "X-Service-Token: your-service-token" \
  -F "document_type=cv" \
  -F "target_degree_hint=master" \
  -F "file=@/absolute/path/to/cv.pdf"
```

---

## Prompt System

Prompts are stored as **JSON templates** in `prompts/` and loaded at runtime with optional context injection. This follows common best practices for versioned, composable LLM prompts.

### Template Structure

Each prompt file follows this shape:

```json
{
  "prompt_template": {
    "base": {
      "agent_identity": { "role": "...", "...": "..." },
      "...": { "...": "..." },
      "output_format": { "format": "json", "...": "..." }
    }
  }
}
```

### Runtime Context Injection

The service merges runtime metadata (document length, user hints, etc.) into the prompt before sending to the LLM:

```python
from app.llm.prompts import get_profile_extraction_prompt

prompt = get_profile_extraction_prompt(
    context={"user_provided_target_degree": "master"},
    fmt="text",  # or "json"
)
```

### Available Prompts

| File                              | Purpose                          |
| --------------------------------- | -------------------------------- |
| `profile_extraction_v1.json`      | Main CV/transcript extraction    |
| `target_degree_detection_v1.json` | Target degree inference          |
| `gap_analysis_v1.json`            | Readiness scan against baselines |

### Prompt Utilities

The `app/utils/prompt_utils.py` module provides:

- `load_prompt_template(filename)` — load raw JSON from disk
- `merge_runtime_context(template, context)` — inject runtime data
- `build_prompt_json(filename, context)` — full pipeline, returns JSON string
- `build_prompt_text(filename, context)` — full pipeline, returns formatted text

---

## Development Workflow

### Code Quality Checks

```bash
# Format code
uv run black app/ tests/
uv run isort app/ tests/

# Lint
uv run flake8 app/ tests/ --max-line-length=120 --extend-ignore=E203,W503,E501
uv run pylint app/ tests/

# Type check
uv run mypy app/ --ignore-missing-imports --no-strict-optional

# Run tests
ALLOW_DB_FAILURE=true USE_MOCK_DATA=true X_SERVICE_TOKEN=test-service-token uv run pytest tests/ -v
```

### Pre-Commit Script

```bash
chmod +x pre-commit-check.sh
./pre-commit-check.sh
```

Runs Black, isort, flake8, pylint, syntax validation, pytest, and mypy in sequence. Pylint and mypy are blocking (the workflow matches this).

---

## Testing

### Run All Tests

```bash
ALLOW_DB_FAILURE=true USE_MOCK_DATA=true X_SERVICE_TOKEN=test-service-token uv run pytest tests/ -v
```

### Run with Coverage

```bash
ALLOW_DB_FAILURE=true USE_MOCK_DATA=true X_SERVICE_TOKEN=test-service-token uv run pytest tests/ --cov=app --cov-report=html -v
open htmlcov/index.html
```

### Test Structure

```
tests/
├── conftest.py                  # Shared fixtures
├── fake_repos.py                # In-memory repository mocks
├── flow/
│   ├── test_parse_clarification_flow.py
│   └── test_profile_crud_flow.py
├── unit/
│   ├── api/
│   │   ├── test_health_and_security_api.py
│   │   └── test_profiles_upload_api.py
│   ├── llm/
│   │   ├── test_llm_prompts.py
│   │   ├── test_llm_retry_count.py
│   │   ├── test_llm_service.py
│   │   └── test_target_degree_clarification.py
│   ├── services/
│   │   ├── test_clarification_and_jobs.py
│   │   ├── test_document_parser.py
│   │   ├── test_gap_analysis_service.py
│   │   ├── test_profile_fields_flow.py
│   │   └── test_profile_service.py
│   └── utils/
│       ├── test_config.py
│       ├── test_logging_redaction.py
│       └── test_prompt_utils.py
```

---

## CI/CD Pipeline

**Workflow**: `.github/workflows/deploy.yml` (named **OuroborosAI Student Profile CI/CD Pipeline** in GitHub)

**Trigger**: Pull requests to `main` or `develop`

Shared lint rules live in `.pylintrc` (line length, a few docstring / design relaxations, similarity thresholds).

### Pipeline Stages

| Stage                | Description                                                          |
| -------------------- | -------------------------------------------------------------------- | --- | ---------------------------- |
| **Format**           | Black + isort validation                                             |
| **Lint**             | **flake8** + **pylint** (both blocking)                              |
| **Unit Tests**       | `pytest tests/unit/` with JUnit XML artifact                         |
| **Type Check**       | **mypy** — blocking (after format + lint)                            |
| **Tests + Coverage** | Full `pytest tests/` with HTML + Cobertura XML (after format + lint) |
| **Security Audit**   | Bandit (JSON artifact; command uses `                                |     | true` to avoid hard-failing) |
| **Docker Build**     | Verify image builds — no push (after all above)                      |
| **Summary**          | Markdown table of all job results                                    |

### Local CI Simulation

```bash
uv run black --check app/ tests/
uv run isort --check-only app/ tests/
uv run flake8 app/ tests/ --max-line-length=120 --extend-ignore=E203,W503,E501
uv run pylint app/ tests/
uv run mypy app/ --ignore-missing-imports --no-strict-optional
ALLOW_DB_FAILURE=true USE_MOCK_DATA=true X_SERVICE_TOKEN=test-service-token uv run pytest tests/ -v
uv run bandit -r app/ || true
docker build -t student-profile-agent .
```

---

## Deployment

### Docker Compose (Full Stack)

```bash
docker compose up --build -d      # start MySQL + service
docker compose logs -f             # follow logs
docker compose down                # stop
docker compose down -v             # stop and remove volumes
```

### Docker (Service Only)

```bash
docker build -t student-profile-agent .

docker run -p 8001:8001 \
  -e DB_HOST=mysql-host \
  -e DB_PASSWORD=secret \
  -e X_SERVICE_TOKEN=token \
  -e OPENAI_API_KEY=sk-... \
  student-profile-agent
```

---

## Project Structure

```
ouroboros-ai-student-profile/
├── app/
│   ├── api/                     # Route handlers (thin layer)
│   │   ├── health.py            # GET / and /health
│   │   ├── profiles.py          # Parse, clarifications, and gap-analysis (+ jobs)
│   │   └── documents.py         # GET /documents/{id}
│   ├── core/                    # Infrastructure
│   │   ├── logging.py           # structlog configuration
│   │   └── security.py          # X-Service-Token validation
│   ├── llm/                     # LLM-specific logic
│   │   ├── prompts.py           # Prompt loading with context injection
│   │   ├── schemas.py           # Pydantic schemas for LLM output
│   │   ├── openai_client.py     # OpenAI client with retry
│   │   └── anthropic_client.py  # Anthropic client with retry
│   ├── middleware/              # Middleware
│   │   ├── service_auth.py      # X-Service-Token dependency
│   │   └── logging_middleware.py
│   ├── models/                  # Pydantic request/response schemas
│   │   ├── common_models.py     # StandardResponse, Pagination
│   │   ├── profile_models.py    # ParseRequest, ProfileResponse
│   │   ├── document_models.py   # DocumentResponse
│   │   └── llm_models.py        # LLMExtractionResult, LLMCallLog
│   ├── repositories/            # Raw SQL data access (aiomysql)
│   │   ├── db_pool.py           # Async MySQL connection pool
│   │   ├── mysql_base.py        # Base repository with helpers
│   │   ├── mysql_profile_repo.py
│   │   ├── mysql_document_repo.py
│   │   ├── mysql_profile_normalized_repo.py
│   │   ├── mysql_field_repo.py
│   │   ├── mysql_gap_analysis_repo.py
│   │   ├── mysql_gap_job_repo.py
│   │   └── mysql_llm_log_repo.py
│   ├── services/                # Business logic
│   │   ├── document_parser.py   # PDF/DOCX/OCR extraction
│   │   ├── llm_service.py       # OpenAI/Anthropic with fallback
│   │   ├── profile_service.py   # Parse -> extract -> store pipeline
│   │   └── gap_analysis_service.py
│   ├── utils/                   # Utilities
│   │   ├── exceptions.py        # Custom exception hierarchy
│   │   ├── trace_id.py          # UUID-v4 trace ID generation
│   │   ├── helpers.py           # generate_uuid, timestamps
│   │   ├── file_utils.py        # File type detection, cleanup
│   │   ├── timezone.py          # UTC helpers
│   │   └── prompt_utils.py      # JSON template loading & context merge
│   ├── config.py                # Pydantic settings
│   └── main.py                  # FastAPI app with lifespan
├── prompts/                     # Version-controlled LLM prompt templates
│   ├── profile_extraction_v1.json
│   ├── target_degree_detection_v1.json
│   └── gap_analysis_v1.json
├── migrations/                  # SQL migration files (001-009)
├── scripts/
│   ├── run_migrations.py
│   └── seed_test_data.py
├── tests/                       # Unit tests + shared fixtures
├── .github/workflows/
│   └── deploy.yml               # CI/CD pipeline
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── .pylintrc
├── .flake8
├── .env.example
├── start.sh
├── pre-commit-check.sh
└── README.md
```

---

## Troubleshooting

### Database Connection Failed

**Symptom**: `RuntimeError: Database pool has not been initialised`

```bash
# Check MySQL is running
docker compose ps

# Test connection
mysql -h localhost -P ${DOCKER_MYSQL_PORT:-3308} -u root -p -e "SHOW DATABASES;"

# Verify credentials
grep DB_ .env
```

### LLM Extraction Failed

**Symptom**: `LLMExtractionError: Both LLM providers failed`

```bash
# Verify provider API keys are set
grep API_KEY .env

# Test OpenAI connectivity
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

### OCR Not Working

**Symptom**: Scanned PDFs return empty text

```bash
# macOS
brew install tesseract

# Ubuntu / Debian
sudo apt-get install tesseract-ocr

# Verify
tesseract --version

# Optionally set path in .env
echo "TESSERACT_PATH=$(which tesseract)" >> .env
```

### Import Errors

**Symptom**: `ModuleNotFoundError: No module named 'app'`

```bash
source .venv/bin/activate
uv sync
```

---

## Attribution

**Developed by**: OuroborosAI Developer Team

**Project**: Ouroboros AI Scholarship Discovery Platform

**Repository**: [github.com/maugus0/ouroboros-ai-student-profile](https://github.com/maugus0/ouroboros-ai-student-profile)
