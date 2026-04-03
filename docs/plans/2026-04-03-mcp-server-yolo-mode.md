# Plan: CEDARS v2 as an MCP Server with Yolo Mode

## Problem & Approach

Add [MCP (Model Context Protocol)](https://modelcontextprotocol.io) support to the CEDARS v2 FastAPI backend so AI agents (Claude, Cursor, Copilot, etc.) can discover and call CEDARS endpoints as structured tools.

Two things are needed:

1. **MCP server** — expose the existing API as MCP tools via `fastapi-mcp`
2. **Yolo mode** — a new "fully automated" pipeline tool designed for agents: runs NLP → LLM → auto-accepts all predictions without human review, returning a results summary

---

## Part A: MCP Integration (`fastapi-mcp`)

**Chosen approach:** [`fastapi-mcp`](https://github.com/tadata-org/fastapi_mcp) (tadata-org, 2025) — the 2025 standard. Mounts an MCP server directly on the FastAPI app using ASGI (in-process, no extra service). Auth is inherited from FastAPI `Depends()`.

**Result:** Any MCP-compatible client connects to `http://localhost:8000/mcp`. All CEDARS routes auto-converted to tools with full Pydantic schemas.

### Phase 1 — Core integration

1. **`backend/pyproject.toml`** — add `fastapi-mcp` dependency (`uv add fastapi-mcp`)

2. **`backend/app/main.py`** — after all routers registered:
   ```python
   from fastapi_mcp import FastApiMCP
   mcp = FastApiMCP(app, name="CEDARS", description="Clinical Event Detection and Recording System — NLP platform for clinical event annotation in EHRs")
   mcp.mount()
   ```
   Exclude admin + internal routes from MCP exposure.

### Phase 2 — LLM ergonomics (clean tool names)

Without explicit `operation_id`, FastAPI generates ugly names like `list_projects_api_v1_projects_get`. Add clean `operation_id` + docstring to ~25 key endpoints:

**`projects/router.py`** — `list_projects`, `create_project`, `get_project`, `get_project_stats`

**`connectors/router.py`** — `list_patients`, `get_patient_notes`, `list_data_sources`

**`annotations/router.py`** — `get_annotation_stats`, `get_next_annotation`, `get_next_patient`, `review_annotation`, `skip_annotation`

**`pipeline/router.py`** — `list_pipeline_runs`, `get_pipeline_run_stats`, `run_sample_pipeline`, `run_full_pipeline`

**`nlp/router.py`** — `get_nlp_stats`, `list_nlp_queries`, `run_nlp_pipeline`

**`export/router.py`** — `get_export_stats`, `export_annotations_json`

**`evaluation/router.py`** — `list_eval_sessions`, `get_eval_metrics`

---

## Part B: Yolo Mode

**What it does:** A single MCP tool that chains the entire pipeline automatically — no human review step. Designed for agents that want fully automated results.

**Workflow:**
```
run_yolo_pipeline(project_id)
  → 1. Trigger NLP pipeline (process all unprocessed notes)
  → 2. Wait / poll for NLP completion
  → 3. Trigger LLM predictions on all target sentences
  → 4. Wait / poll for LLM completion
  → 5. Auto-accept all predictions:
         LLM=positive → mark reviewed with predicted event date
         LLM=negative/inconclusive → skip annotation
  → 6. Return summary: {patients_processed, events_found, annotations_reviewed, export_url}
```

### Phase 3 — Yolo mode implementation

3. **New ARQ task: `backend/app/worker.py`** — add `run_yolo_pipeline_task(ctx, project_id, user_id)`:
   - Runs NLP job (calls existing `run_nlp` service)
   - Polls until NLP complete
   - Runs LLM prediction job (calls existing `dispatch_prediction_job` service)
   - Polls until predictions complete
   - Iterates all unreviewed annotations: calls `review_annotation` (positive) or `skip_annotation` (negative/inconclusive)
   - Returns `YoloPipelineResult` summary

4. **New endpoint in `backend/app/pipeline/router.py`** (or new `yolo/router.py`):
   - `POST /api/v1/projects/{project_id}/pipeline/yolo` — dispatches yolo background task, returns `{job_id}`
   - `GET /api/v1/projects/{project_id}/pipeline/yolo/status` — polls status and returns result when done
   - `operation_id="run_yolo_pipeline"` / `operation_id="get_yolo_pipeline_status"`

5. **New Pydantic schemas** — `YoloPipelineResult`:
   ```python
   class YoloPipelineResult(BaseModel):
       patients_processed: int
       events_found: int
       annotations_reviewed: int
       annotations_skipped: int
       export_url: str  # link to /export/annotations
   ```

6. **Register yolo router in `main.py`** — include new router

---

## Phase 4 — Documentation

7. **Update `CLAUDE.md`** — add MCP section with:
   - Connection URL: `http://localhost:8000/mcp`
   - Claude Desktop config snippet
   - Yolo mode description and usage

8. **Add `backend/mcp.json`** — Claude Desktop config example

---

## Files Changed

| File | Change |
|------|--------|
| `backend/pyproject.toml` | Add `fastapi-mcp` dependency |
| `backend/app/main.py` | Mount `FastApiMCP`, register yolo router |
| `backend/app/projects/router.py` | Add `operation_id` + docstrings |
| `backend/app/connectors/router.py` | Add `operation_id` + docstrings |
| `backend/app/annotations/router.py` | Add `operation_id` + docstrings |
| `backend/app/pipeline/router.py` | Add `operation_id` + docstrings |
| `backend/app/nlp/router.py` | Add `operation_id` + docstrings |
| `backend/app/export/router.py` | Add `operation_id` + docstrings |
| `backend/app/evaluation/router.py` | Add `operation_id` + docstrings |
| `backend/app/worker.py` | Add `run_yolo_pipeline_task` ARQ task |
| `backend/app/pipeline/router.py` | Add yolo endpoints (or new `yolo/router.py`) |
| `backend/app/pipeline/schemas.py` | Add `YoloPipelineResult` schema |
| `CLAUDE.md` | MCP docs section |
| `backend/mcp.json` | Claude Desktop config example |

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Library | `fastapi-mcp` | Native FastAPI, ASGI transport, auto-schema, auth inheritance |
| Deployment | Same process as FastAPI | No extra infra; ASGI is in-process |
| MCP endpoint | `/mcp` | Default from fastapi-mcp |
| Auth | JWT cookie (existing) | Clients call `/api/v1/auth/login` first |
| Yolo task | ARQ background task | Pipeline is long-running; keeps HTTP non-blocking |
| Admin routes | Excluded from MCP | Not for agent consumption |
| Yolo auto-accept logic | positive→review, negative/inconclusive→skip | Matches expected agent use case |

## Notes

- `fastapi-mcp` requires Python 3.10+ and FastAPI 0.115+ — both already satisfied
- WebSocket endpoints are not exposed as MCP tools (incompatible transport)
- Yolo mode is additive — no existing functionality changed
- Yolo can be run after a manual pipeline run too (it only touches unreviewed annotations)
