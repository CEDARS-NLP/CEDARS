# CEDARS v2 Platform Redesign

**Date:** 2026-03-03
**Status:** Approved
**Author:** R. Singh + Claude

## Overview

Full reimplementation of CEDARS from a single-project Flask/MongoDB application to a multi-tenant platform built on FastAPI, React, and PostgreSQL. Unifies the LLM and PINES/BERT prediction systems under a single evaluation framework with learning loops.

## Motivation

- **Technical debt**: God modules (db.py ~2,400 lines, ops.py ~1,300 lines), circular imports, global state coupling
- **Frontend**: Jinja2 + vanilla JS limits interactivity; annotation UI needs keyboard-driven SPA
- **Architecture**: Single-project-per-instance doesn't scale for institutional use (MSK) or external distribution
- **Evaluation gap**: PINES/BERT has no evaluation framework; LLM evaluation exists but is siloed

## Approach

Strangler fig migration — build new system alongside existing, migrate one domain at a time. Always have a working system.

---

## Architecture

### High-Level

```
┌─────────────────────────────────────────────────────────┐
│                      CEDARS Platform                     │
│                                                          │
│  ┌──────────────┐    ┌───────────────────────────────┐  │
│  │  React SPA   │◄──►│       FastAPI Backend          │  │
│  │  (TypeScript) │    │  ┌─────────┬────────────────┐ │  │
│  └──────────────┘    │  │  Auth   │  API Routes     │ │  │
│                      │  │ (JWT)   │  /api/v1/...    │ │  │
│                      │  └─────────┴────────────────┘ │  │
│                      └──────────┬────────────────────┘  │
│                                 │                        │
│              ┌──────────────────┼──────────────────┐    │
│              ▼                  ▼                  ▼    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  PostgreSQL   │  │    Redis     │  │ S3-compat    │  │
│  │  (data)       │  │  (queue +   │  │ (files)      │  │
│  │               │  │   cache)    │  │              │  │
│  └──────────────┘  └──────┬──────┘  └──────────────┘  │
│                           │                             │
│                    ┌──────┴──────┐                      │
│                    │  Workers    │                      │
│                    │  (unified   │                      │
│                    │   pool)     │                      │
│                    └─────────────┘                      │
│                                                          │
│  ┌──────────────────┐  (optional)                       │
│  │  PINES Service   │                                   │
│  └──────────────────┘                                   │
└─────────────────────────────────────────────────────────┘
```

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Backend | FastAPI | Async-native, Pydantic-first, OpenAPI auto-docs, unifies with PINES |
| Frontend | React + TypeScript | Rich annotation UIs, component ecosystem, strong typing |
| Database | PostgreSQL | ACID, JSONB for flexible metadata, full-text search, Alembic migrations |
| ORM | SQLAlchemy 2.0 + SQLModel | Type-safe, async support, FastAPI-native |
| Queue | ARQ (async Redis queue) | Single worker pool with queue routing. Async-native for FastAPI. |
| Object Storage | S3-compatible (boto3) | Works with AWS S3, MinIO, GCS S3-compat mode |
| Auth | JWT (built-in) | SSO (OIDC/SAML) deferred to v2 |
| API | REST with OpenAPI | Auto-generated docs, client SDK generation |
| Multi-tenancy | Shared DB, logical isolation | project_id scoping, row-level access control |
| Deployment | Docker Compose | K8s/Helm deferred to v2 |
| Security | Secure by default | TLS, audit logging, RBAC, soft deletes — always on |

### Platform Model

Current: One project = one deployed instance.
New: One instance = many projects, many users.

```
Platform Instance
├── Users (with roles: platform_admin, project_admin, annotator, viewer)
├── Project A
│   ├── Members (user-project role assignments)
│   ├── Data Sources (connectors)
│   ├── Notes (clinical data, scoped to project)
│   ├── Annotations
│   ├── Predictor Configs (LLM and/or PINES)
│   ├── Evaluation Sessions
│   └── Exports
├── Project B ...
└── Project C ...
```

---

## Data Model (PostgreSQL)

```sql
-- Platform
users           (id, email, password_hash, name, role, created_at)
projects        (id, name, description, owner_id, created_at, settings JSONB)
project_members (project_id, user_id, role)

-- Data Sources (plugin-based connectors)
data_sources    (id, project_id, connector_type, config JSONB, credentials_encrypted, last_sync)

-- Clinical Data
patients        (id, project_id, patient_id_ext, status, locked_by, locked_at, metadata JSONB)
notes           (id, project_id, patient_id, note_date, text, metadata JSONB, source_ref)
sentences       (id, note_id, text, start_pos, end_pos, is_negated, is_target)

-- Prediction
predictor_configs (id, project_id, type, name, config JSONB, created_by, created_at)
predictions     (id, sentence_id, predictor_config_id, score, label, reasoning, created_at)
annotations     (id, sentence_id, user_id, judgment, comment, created_at)

-- Unified Evaluation
evaluation_sessions (id, project_id, predictor_config_id, sample_config JSONB,
                     status, metrics JSONB, created_by, created_at)
evaluation_judgments (id, session_id, note_id, note_text,
                      prediction_label, prediction_score, prediction_reasoning,
                      judgment, judged_by, judged_at)
validated_predictors (id, project_id, predictor_config_id, evaluation_session_id,
                      version_name, metrics JSONB, threshold, is_active,
                      validated_by, validated_at)

-- Learning Loop Data
predictor_examples  (id, project_id, predictor_config_id, note_text, correct_label,
                     source_session_id, error_type, is_active, created_at)
training_datasets   (id, project_id, name, format, source_session_ids JSONB,
                     example_count, artifact_path, created_at)

-- NLP
search_queries  (id, project_id, regex_pattern, is_active)

-- Audit
audit_log       (id, user_id, action, entity_type, entity_id, diff JSONB, created_at)

-- All clinical data tables have deleted_at for soft deletes
-- All project-scoped tables enforce project_id in queries
```

---

## Backend Structure

```
backend/
├── app/
│   ├── main.py                  # FastAPI app factory
│   ├── config.py                # Settings via pydantic-settings
│   ├── dependencies.py          # DI: DB sessions, current user, permissions
│   ├── auth/                    # /api/v1/auth/*
│   ├── projects/                # /api/v1/projects/*
│   ├── data/                    # /api/v1/projects/{id}/data/*
│   ├── connectors/              # Plugin system
│   │   ├── base.py              # ConnectorBase ABC
│   │   ├── registry.py          # Plugin discovery & registration
│   │   ├── file_upload.py       # Built-in
│   │   └── databricks.py        # Built-in
│   ├── nlp/                     # /api/v1/projects/{id}/nlp/*
│   ├── predictors/              # /api/v1/projects/{id}/predictors/*
│   │   ├── base.py              # BasePredictor ABC
│   │   ├── llm.py               # LLM via LiteLLM
│   │   └── pines.py             # PINES client
│   ├── annotations/             # /api/v1/projects/{id}/annotations/*
│   ├── evaluation/              # /api/v1/projects/{id}/evaluation/*
│   ├── export/                  # /api/v1/projects/{id}/export/*
│   └── common/
│       ├── database.py          # SQLAlchemy engine, sessions
│       ├── storage.py           # S3-compatible abstraction
│       ├── security.py          # Permission checks
│       └── exceptions.py
├── migrations/                  # Alembic
├── workers/                     # Unified worker pool with queue routing
├── tests/
├── pyproject.toml               # uv managed
└── Dockerfile
```

### Patterns

- **Service layer**: Routers parse request → call service → return response. All business logic in service modules.
- **Dependency injection**: FastAPI `Depends()` for DB sessions, current user, permissions, storage.
- **No god modules**: Each domain self-contained (models, schemas, service, router).
- **Unified worker pool**: Single worker type with ARQ queue routing (tasks vs ops queues).

---

## Frontend Structure

```
frontend/
├── src/
│   ├── api/generated/           # Auto-generated from OpenAPI
│   ├── auth/                    # Login, register, auth context
│   ├── projects/                # Project list, create, layout
│   ├── data/                    # Connector config, upload, preview, ingestion status
│   ├── nlp/                     # Search query config, pipeline status
│   ├── predictors/              # Predictor config (LLM + PINES)
│   ├── annotations/             # Adjudication UI (keyboard-driven)
│   ├── evaluation/              # Sampling, review, dashboard, comparison
│   ├── export/                  # Download results
│   ├── common/                  # Shared components, hooks, layouts
│   └── lib/                     # Utilities
├── package.json
├── vite.config.ts
└── Dockerfile
```

### Tech Choices

| Component | Choice |
|-----------|--------|
| Build tool | Vite |
| Routing | React Router v6+ |
| State | TanStack Query (server-state) |
| UI library | shadcn/ui + Tailwind CSS |
| API client | Auto-generated from OpenAPI |
| Forms | React Hook Form + Zod |
| Charts | Recharts |
| Real-time | WebSocket for job progress + annotation notifications |

---

## Data Connectors

### Plugin Architecture

```
app/connectors/
├── base.py         # ConnectorBase ABC: connect, list_tables, preview, fetch, validate
├── registry.py     # Plugin discovery & registration
├── file_upload.py  # Built-in: CSV, Excel, JSON, Parquet from S3
└── databricks.py   # Built-in: Databricks SQL warehouse
```

- Admin configures data source per project (connection config, credentials, table/view selection)
- Credentials encrypted at rest
- Preview mode before import
- Batch-streamed ingestion (1000-row chunks)
- Future connectors (Snowflake, BigQuery, FHIR) added as new files — same interface

---

## NLP Pipeline

Keep spaCy for preprocessing; LLM-first for classification.

```
Clinical Note → spaCy (sentence split, tokenize, regex match, negation detect)
             → Candidate sentences
             → LLM classification (primary) or PINES (optional)
             → Auto-adjudication (threshold)
             → Human review of remaining
```

spaCy is pluggable — interface allows replacement with alternative NLP backends in the future.

---

## Unified Evaluation Framework

### The Core Insight

Every predictor (PINES, LLM, or future) goes through the same evaluation lifecycle:

```
CONFIGURE → EVALUATE → VALIDATE → ACTIVATE → DEPLOY
```

### Unified Workflow

1. **Configure predictors** — Admin adds LLM config and/or PINES config to project
2. **Create evaluation session** — Select any predictor config, configure sampling (size, keywords, ratio)
3. **Run predictions** — Background job calls `predictor.predict()` for each sampled note (same interface for all types)
4. **Human review** — Annotator judges each prediction (correct/wrong/skip). See reasoning if available (LLM).
5. **Analyze** — Metrics dashboard (P/R/F1/accuracy). Compare across predictor types on same sample.
6. **Validate** — Snapshot config + metrics + threshold as ValidatedPredictor
7. **Activate** — One active predictor per project, used for production pipeline

### Comparison View

Run multiple evaluation sessions on the same sample, compare side-by-side:

```
┌─────────────────┬───────┬───────┬───────┬──────────┐
│ Predictor       │ Prec  │ Rec   │ F1    │ Cost/note │
├─────────────────┼───────┼───────┼───────┼──────────┤
│ GPT-4o (v2)     │ 0.94  │ 0.91  │ 0.92  │ $0.012   │
│ GPT-4o-mini     │ 0.88  │ 0.85  │ 0.86  │ $0.002   │
│ PINES (v1)      │ 0.82  │ 0.79  │ 0.80  │ $0.00    │
│ Ollama llama3   │ 0.86  │ 0.83  │ 0.84  │ $0.00    │
└─────────────────┴───────┴───────┴───────┴──────────┘
```

Disagreement analysis: drill into notes where predictors disagree.

### Threshold Optimization

Threshold is validated alongside the predictor. Evaluation UI shows how metrics change with threshold:

```
Threshold │ Auto-dismissed │ Precision │ Recall │ F1
0.70      │ 45%           │ 0.85      │ 0.95   │ 0.90
0.80      │ 62%           │ 0.90      │ 0.91   │ 0.90
0.90      │ 81%           │ 0.95      │ 0.82   │ 0.88
```

---

## Learning Loops

### LLM Prompt Evolution Loop

```
Predict → Human reviews → Analyze error patterns → Refine prompt → Re-evaluate → Repeat
```

Mechanisms:
- **Few-shot example bank**: Store corrected examples. Auto-select relevant N examples for prompt based on error coverage.
- **Error pattern analysis**: Cluster wrong predictions by theme. Surface patterns.
- **Prompt diff suggestions**: When patterns are clear, suggest specific prompt edits.
- **A/B evaluation**: Old vs new prompt on same sample, side-by-side metrics.

### PINES/BERT Active Learning Loop

```
Predict → Uncertainty sampling → Prioritize uncertain notes for human review → Collect labels → Export for retraining → Re-evaluate → Repeat
```

Strategies:
- **Uncertainty sampling**: Prioritize notes where `abs(score - 0.5)` is smallest
- **Disagreement sampling**: Prioritize notes where PINES and LLM disagree
- **Error-driven sampling**: Prioritize notes similar to known errors

### Training Data Collection & Export

The platform collects all data needed for DPO/KTO/SFT fine-tuning:
- Evaluation judgments = preference data (correct/wrong on model predictions)
- Few-shot example bank = curated training examples
- Export in HuggingFace-compatible formats (DPO pairs, KTO binary, SFT)

**Training is offline in v1** — admin exports data, trains using TRL/Axolotl/unsloth on separate GPU infrastructure, uploads fine-tuned model (LoRA adapter) to serve via Ollama or vLLM.

Supported RLHF techniques (offline):
- **DPO** (Direct Preference Optimization) — best for preference pairs
- **KTO** (Kahneman-Tversky Optimization) — works with binary feedback
- **ORPO** — combines SFT + preference in one step
- **SFT** — supervised fine-tuning on correct examples

### Cross-Predictor Synergy

LLM and PINES feedback loops reinforce each other:
- LLM reasoning explains why PINES got something wrong
- PINES provides cheap bulk scoring to identify where LLM evaluation should focus
- Disagreement detection feeds both learning loops
- Human feedback from either predictor's evaluation can feed the other's training data

---

## Security

Built secure by default — no compliance tiers.

| Layer | Measure |
|-------|---------|
| Data at rest | PostgreSQL volume encryption. S3 server-side encryption. |
| Data in transit | TLS on all connections (API, DB, Redis, S3). |
| PHI in LLM calls | `allow_cloud_llm` flag per project. Local providers (Ollama) keep data on-premises. |
| Access control | RBAC: platform_admin, project_admin, annotator, viewer. All data project-scoped. |
| Audit logging | Append-only audit_log table. Every PHI read/write logged. |
| Soft deletes | `deleted_at` timestamp, never hard delete clinical data. |
| Session management | Short-lived JWT access tokens (15min), refresh tokens (7d), Redis revocation list. |
| LLM security | Prompt injection protection (XML sanitization), per-project API call budgets. |
| Credentials | Connection credentials encrypted at rest. API keys from env vars only. |

---

## Annotation UI

Keyboard-driven SPA for efficient annotation:

```
┌────────────────────────────────────────────────────────┐
│  CEDARS  │ Project: MI Study  │ ■■■■■■□□□□ 63%       │
├──────────┴─────────────────────┴──────────────────────┤
│                                                        │
│  Patient: P-10432          Note: 2024-03-15           │
│                                                        │
│  Context (prior sentences):                            │
│  │ Patient presented with chest pain radiating to     │
│  │ left arm. ECG showed ST elevation in leads II...   │
│                                                        │
│  ► TARGET SENTENCE:                                    │
│  ┌──────────────────────────────────────────────────┐ │
│  │ Troponin levels were elevated at 2.4 ng/mL,      │ │
│  │ consistent with acute myocardial infarction.      │ │
│  └──────────────────────────────────────────────────┘ │
│                                                        │
│  LLM Prediction: POSITIVE (0.94)                      │
│  Reasoning: "Elevated troponin with ST elevation      │
│  meets criteria for confirmed MI"                      │
│                                                        │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐              │
│  │ Accept  │  │ Reject  │  │  Skip   │              │
│  │   (Y)   │  │   (N)   │  │   (S)   │              │
│  └─────────┘  └─────────┘  └─────────┘              │
│  ◄ Prev (K)                          Next (J) ►      │
└────────────────────────────────────────────────────────┘
```

- Keyboard shortcuts: Y/N/S for judgment, J/K for navigation
- Patient timeline view with surrounding notes
- LLM reasoning visible alongside prediction
- Database-backed state (survives browser close)
- WebSocket live progress updates

---

## Deployment (v1)

Docker Compose with profiles:

```yaml
services:
  frontend:    # Nginx serving React SPA
  backend:     # FastAPI on Uvicorn
  db:          # PostgreSQL 16 (with healthcheck)
  redis:       # Redis 7 (with healthcheck)
  worker:      # Unified ARQ worker pool (task + ops queues)
  minio:       # S3-compatible storage (optional, omit for AWS S3)
  pines:       # PINES service (optional, profile: pines)
  prometheus:  # Metrics
  nginx:       # Reverse proxy
```

Profiles:
- `default` — Full stack with MinIO (self-hosted)
- `aws` — No MinIO (uses AWS S3), no local DB (uses RDS)
- `pines` — Adds PINES service

### Storage Abstraction

S3-compatible via boto3. Configure via env vars:
- `S3_ENDPOINT` — MinIO URL or AWS S3 endpoint
- `S3_BUCKET` — Bucket name
- `S3_ACCESS_KEY`, `S3_SECRET_KEY` — Credentials
- Works with AWS S3, MinIO, GCS (S3-compat mode)

---

## Migration Strategy

### MongoDB → PostgreSQL Migration Tool

```
backend/migrations/mongo_to_postgres.py

Phase 1: Schema (Alembic creates tables)
Phase 2: Data migration per project:
  INFO         → projects + predictor_configs
  USERS        → users + project_members
  NOTES        → patients + notes
  ANNOTATIONS  → sentences + annotations
  PINES        → predictions
  EVAL_*       → evaluation_sessions + judgments
  VAL_PROMPTS  → validated_predictors
Phase 3: Validation (row counts, spot checks)
```

### Strangler Fig Migration Order

1. Auth + user management
2. Project management + configuration
3. Upload/ingestion pipeline
4. LLM predictor system
5. Adjudication UI
6. Evaluation framework
7. NLP pipeline + PINES
8. Remove Flask app

---

## Monitoring

| Layer | Tool |
|-------|------|
| Infrastructure | Prometheus + Grafana (API latency, queue depth, DB connections) |
| Prediction quality | Built-in dashboards (accuracy over time, auto-dismiss rate) |
| LLM costs | Built-in tracking (cost per prediction, per-project budgets) |
| Audit | PostgreSQL audit_log (all PHI access, all admin actions) |

Drift detection and automated alerting deferred to v2.

---

## v2 Roadmap (Deferred)

- OIDC/SAML SSO for institutional identity providers
- Kubernetes Helm charts for large institutional deployments
- AWS-native deployment option (ECS/EKS + RDS + S3)
- In-platform GPU training (DPO/KTO via TRL)
- Automated drift detection and alerting
- De-identification plugin for PHI stripping
- Additional connectors (Snowflake, BigQuery, FHIR)
- Pluggable NLP backends (alternative to spaCy)
- R package / programmatic API for researchers

---

## Reference Architectures

- [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) — FastAPI + React + PostgreSQL + SQLModel. Our design aligns closely.
- [Label Studio](https://github.com/HumanSignal/label-studio) — Multi-project annotation platform. Reference for multi-tenancy, connector patterns, and annotation UI.
