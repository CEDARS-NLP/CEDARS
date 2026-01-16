# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CEDARS (Clinical Event Detection and Recording System) is a Python-based platform for NLP-powered clinical event detection in electronic health records (EHR). It has two main components:

- **CEDARS** (`cedars/`): Flask web application for data labeling and annotation
- **PINES** (`PINES/`): FastAPI service for NLP model inference (Longformer-based clinical text classification)

## Build & Development Commands

### CEDARS (Flask App)
```bash
cd cedars
poetry install                                    # Install dependencies
poetry run python -m gunicorn -c gunicorn.conf.py app.wsgi:create_app()  # Run app
poetry run pytest                                 # Run all tests
poetry run pytest tests/test_file.py::test_name -v  # Run single test
poetry run pytest --cov=app                       # Run with coverage
poetry run flake8 ./                              # Lint
```

### PINES (FastAPI NLP Service)
```bash
cd PINES
poetry install
poetry run python pines.py                        # Run locally
poetry run pytest                                 # Run tests
```

### Docker Deployment
```bash
# Profiles: cpu, gpu, selfhosted, superbio
docker compose --profile selfhosted up --build   # Full local stack with MongoDB
docker compose --profile cpu up --build          # Without local MongoDB
```

## Architecture

### Service Stack (docker-compose.yml)
- **web**: Flask app on Gunicorn (port 5001 internal, nginx proxy on 80)
- **db**: MongoDB (selfhosted/superbio profiles only)
- **redis**: Background job queue with RQ (Redis Queue)
- **worker-task**: RQ workers for NLP processing tasks
- **worker-ops**: RQ worker for operational tasks (single instance)
- **pines/pines-gpu**: PINES NLP inference service
- **minio**: Object storage for file uploads
- **prometheus**: Metrics collection
- **nginx**: Reverse proxy

### CEDARS App Structure (`cedars/app/`)
- `__init__.py`: Flask app factory with blueprint registration
- `ops.py`: Main operations blueprint - project management, annotation UI, file upload
- `db.py`: MongoDB operations layer (patients, notes, annotations, users)
- `auth.py`: Authentication with flask-login
- `nlpprocessor.py`: NLP pipeline (spaCy, negation detection)
- `adjudication_handler.py`: Annotation review logic
- `api.py`: PINES API integration
- `stats.py`: Statistics blueprint
- `cedars_enums.py`: Status enums (PatientStatus, ReviewStatus)

### Data Flow
1. Clinical notes uploaded via web UI → stored in MongoDB + MinIO
2. NLP pipeline processes notes (spaCy tokenization, NegEx)
3. Optionally calls PINES API for model-based classification
4. Annotators review sentences via GUI
5. Annotations stored in MongoDB

### Configuration
- Environment: `.env` file (see `.env.sample`)
- Flask configs: `cedars/config.py` (Base, Local, Test, Dev, Prod classes)
- Key env vars: `DB_HOST`, `DB_NAME`, `REDIS_URL`, `PINES_API_URL`, `MINIO_*`

## Testing

Tests use pytest with mocked dependencies:
- **mongomock**: MongoDB mocking
- **fakeredis**: Redis mocking
- **pytest-minio-mock**: MinIO mocking

Test fixtures in `cedars/tests/conftest.py` set up app context, mock database, and authenticated test client.

Required env var for tests: `PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus-multiproc`

## Code Conventions

- **Imports**: Standard library → third-party → local modules
- **Naming**: CamelCase classes, snake_case functions/variables, UPPER_SNAKE_CASE constants
- **Typing**: Use Python type hints where appropriate
- **Enums**: Class-based pattern in `app/cedars_enums.py`
- **Docstrings**: Use triple quotes for functions and classes
- **Error Handling**: Use try/except blocks with specific exceptions
- **Framework**: Flask 3.x, flask-pymongo, flask-login, RQ for background jobs

---

## Known Anti-Patterns & Technical Debt

### Critical Issues

| Anti-Pattern | Location | Description |
|--------------|----------|-------------|
| **God Module** | `db.py` (~2,200 lines) | Mixes data access, business logic, NLP coordination, queue management. Should be split into repository + service layers. |
| **Fat Route Handlers** | `ops.py` | Route handlers contain business logic (80+ lines). Extract to service functions. |
| **Circular Imports** | `database.py:22-24` | Imports `db`, `nlpprocessor`, `api` creating circular dependency risk. |
| **Global State Coupling** | Throughout | Direct module imports instead of dependency injection. Hard to test and mock. |
| **Session as State Machine** | `ops.py:718+` | Flask session stores complex annotation state. Should use database or dedicated state management. |

### Configuration Issues

| Issue | Impact |
|-------|--------|
| Config loaded 3x | `config.py`, `make_rq.py`, `ops.py` each call `dotenv_values(".env")` |
| PINES has 3 connection modes | `PINES_API_URL`, `SUPERBIO_API_URL`, and docker service - confusing |
| `worker-ops` hardcoded scale: 1 | Cannot scale ops queue workers (bottleneck for bulk operations) |

### Infrastructure Issues

| Issue | Location | Impact |
|-------|----------|--------|
| Missing `depends_on: db` | docker-compose workers | Workers may start before DB ready |
| No health checks | web, db, pines services | Cascading failures on startup |
| Prometheus misconfigured | prometheus.yml | Scrapes nginx instead of web directly |

---

## Refactoring Roadmap

### Phase 1: Configuration Cleanup (Low Risk)
1. Ensure `.env.sample` has all required variables
2. Centralize config loading - single `dotenv_values()` call in `config.py`, import elsewhere
3. Add startup validation for required config vars
4. Standardize PINES connection to single mode (docker service OR remote, not both)

### Phase 2: Split db.py (Medium Risk)
Target structure:
```
app/
├── repositories/          # Data access only
│   ├── patient_repository.py
│   ├── note_repository.py
│   ├── annotation_repository.py
│   └── user_repository.py
├── services/              # Business logic
│   ├── patient_service.py
│   ├── annotation_service.py
│   └── nlp_service.py
└── db.py                  # Thin facade for backwards compatibility
```

### Phase 3: Extract Service Layer from ops.py (Medium Risk)
1. Move business logic from route handlers to service functions
2. Routes should only: parse request → call service → format response
3. Services handle: validation, business rules, orchestration

### Phase 4: Infrastructure Hardening (Low Risk)
1. Add health checks to all docker-compose services
2. Add `depends_on` with `condition: service_healthy` for proper startup order
3. Fix or remove Prometheus configuration
4. Make `worker-ops` scale configurable (use Redis locks for race conditions)

### Phase 5: Dependency Injection (Higher Risk)
1. Create application context that holds dependencies
2. Inject repositories/services into route handlers
3. Enables proper unit testing without extensive mocking

---

## Multi-Database Architecture (NEW)

CEDARS now supports both MongoDB and SQLite backends via the repository pattern.

### Configuration

Set `DB_TYPE` in `.env`:
```bash
# For MongoDB (default)
DB_TYPE=mongodb

# For SQLite
DB_TYPE=sqlite
SQLITE_DB_PATH=cedars.db
```

### Using Repositories (Recommended for new code)

```python
from app.factory import get_patient_repository, get_note_repository

# Get repository for configured backend
patient_repo = get_patient_repository()
note_repo = get_note_repository()

# Use repository methods
patient = patient_repo.get_by_id("P001")
notes = note_repo.get_by_patient("P001")
```

### Architecture

```
app/
├── models/              # Pydantic models (shared)
├── repositories/
│   ├── interfaces/      # Abstract base classes
│   ├── mongo/           # MongoDB implementations
│   └── sqlite/          # SQLite implementations
├── factory.py           # Repository factory (selects backend)
├── db_facade.py         # Backwards-compatible facade
└── db.py                # Legacy (being migrated)
```

### Migration Status

- [x] Pydantic models created
- [x] Repository interfaces defined
- [x] MongoDB repositories implemented
- [x] SQLite repositories implemented
- [x] Factory pattern implemented
- [ ] Full db.py migration (in progress - use db_facade.py for new code)
