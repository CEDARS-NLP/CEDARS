# Unified Evaluation Session — Phase 3: Backend Router & API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old evaluation + pipeline routers with a unified evaluation session router exposing all endpoints from the design spec.

**Architecture:** New router in `backend/app/evaluation/router.py` replaces the old one. Adds query suggestion endpoint using adapted `pattern_generator.py`. Pipeline run endpoints (cancel, retry, stats) delegate to `pipeline/orchestrator.py`. WebSocket for LLM progress. Old pipeline router kept but only for legacy run monitoring.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async, LiteLLM, WebSocket

---

## File Structure

| Action | File | Purpose |
|--------|------|---------|
| Rewrite | `backend/app/evaluation/router.py` | All unified session API endpoints |
| Create | `backend/app/evaluation/query_suggest.py` | LLM-powered query suggestion (adapted from pattern_generator) |
| Create | `backend/app/evaluation/ws.py` | WebSocket for LLM sample run progress |
| Create | `backend/tests/test_eval_router.py` | Router integration tests |
| Modify | `backend/app/main.py:82` | Remove old pipeline_router import if fully replaced |

---

### Task 7: Query Suggestion Endpoint

**Files:**
- Create: `backend/app/evaluation/query_suggest.py`
- Test: `backend/tests/test_eval_router.py` (partial — suggestion tests)

- [ ] **Step 1: Write failing test for query suggestion**

```python
# backend/tests/test_eval_router.py
import pytest
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def auth_client(app):
    """Authenticated client: register + login, return client with cookies."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register
        await client.post("/api/v1/auth/register", json={
            "email": "test@test.com", "password": "testpass123", "name": "Test",
        })
        # Login
        resp = await client.post("/api/v1/auth/login", json={
            "email": "test@test.com", "password": "testpass123",
        })
        assert resp.status_code == 200
        yield client


@pytest.fixture
async def project_id(auth_client):
    resp = await auth_client.post("/api/v1/projects", json={"name": "TestProject"})
    assert resp.status_code == 201
    return resp.json()["id"]


class TestQuerySuggestion:
    async def test_suggest_queries_returns_suggestions(self, auth_client, project_id):
        # Create a session first
        resp = await auth_client.post(
            f"/api/v1/projects/{project_id}/evaluation/sessions",
            json={"search_queries": []},
        )
        assert resp.status_code == 201
        session_id = resp.json()["id"]

        with patch(
            "app.evaluation.query_suggest.suggest_queries",
            new_callable=AsyncMock,
            return_value=[
                {"query": "troponin OR MI", "type": "include"},
                {"query": "(ECG OR EKG) AND elevation", "type": "include"},
                {"query": "!suspected", "type": "exclude"},
            ],
        ):
            resp = await auth_client.post(
                f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/queries/suggest",
                json={
                    "description": "Myocardial infarction with troponin elevation",
                    "llm_provider": "openai",
                    "llm_model": "gpt-4o-mini",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["suggestions"]) == 3
            assert data["suggestions"][0]["query"] == "troponin OR MI"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_eval_router.py::TestQuerySuggestion -v -x`
Expected: FAIL (router doesn't exist yet)

- [ ] **Step 3: Write the query suggestion module**

```python
# backend/app/evaluation/query_suggest.py
"""LLM-powered query suggestion for evaluation sessions.

Generates clinician-friendly search queries (spaCy Matcher syntax)
from a natural language event description.
"""

import json
import logging
import re

import litellm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a clinical NLP expert. Given a clinical event description, generate search queries to find relevant mentions in clinical notes.

Use this query syntax:
- `term1 OR term2` — match notes containing either term
- `(term1 OR term2) AND term3` — both conditions in same note
- `embol*` — wildcard: matches embolism, emboli, embolus, etc.
- `!term` — exclude notes containing this term

Rules:
- Generate include queries (to find relevant notes) and exclude queries (to filter noise)
- Use terms clinicians actually write in notes, including abbreviations
- Include common misspellings and variations
- Keep queries simple and focused — one concept per query
- Prefer wildcards for word stems (e.g., `thromb*` instead of listing all variants)

Respond ONLY with a JSON array:
[
  {"query": "troponin OR MI", "type": "include"},
  {"query": "(ECG OR EKG) AND elevation", "type": "include"},
  {"query": "!suspected", "type": "exclude"}
]"""


def _build_litellm_model(provider: str, model: str) -> str:
    if provider == "ollama":
        return f"ollama/{model}"
    if provider == "bedrock":
        return f"bedrock/{model}"
    if provider in ("vllm", "lmstudio", "tgi", "openai_compatible"):
        return f"openai/{model}"
    return model


def _build_connection_kwargs(provider: str, api_base: str | None) -> dict:
    kwargs: dict = {}
    if api_base:
        api_base = api_base.rstrip("/")
        if provider in ("vllm", "lmstudio", "tgi", "openai_compatible") and not api_base.endswith("/v1"):
            api_base = api_base + "/v1"
        kwargs["api_base"] = api_base
    if provider in ("ollama", "vllm", "lmstudio", "tgi", "openai_compatible"):
        kwargs["api_key"] = "no-key-required"
    return kwargs


def _parse_json_response(content: str) -> list[dict]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"```(?:json)?\s*", "", content)
        content = content.rstrip("`").strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            raise ValueError(f"Could not parse LLM response as JSON: {content[:200]}")

    if not isinstance(data, list):
        raise ValueError("Expected JSON array of query suggestions")
    return data


async def suggest_queries(
    description: str,
    llm_provider: str,
    llm_model: str,
    llm_api_base: str | None = None,
) -> list[dict]:
    """Generate search query suggestions from a natural language event description.

    Returns list of dicts: [{"query": "...", "type": "include|exclude"}, ...]
    Raises ValueError on LLM or parsing errors.
    """
    user_prompt = f"""Generate search queries to find this clinical event in patient notes:

{description}

Respond with a JSON array only."""

    model_str = _build_litellm_model(llm_provider, llm_model)
    conn_kwargs = _build_connection_kwargs(llm_provider, llm_api_base)

    try:
        response = await litellm.acompletion(
            model=model_str,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            timeout=60,
            **conn_kwargs,
        )
    except Exception as e:
        raise ValueError(f"Query suggestion failed: {e}") from e

    content = response.choices[0].message.content or ""
    suggestions = _parse_json_response(content)

    # Validate each suggestion has required fields
    validated = []
    for s in suggestions:
        if isinstance(s, dict) and "query" in s:
            validated.append({
                "query": str(s["query"]),
                "type": s.get("type", "include"),
            })
    return validated
```

- [ ] **Step 4: Commit**

```bash
cd backend
git add app/evaluation/query_suggest.py
git commit -m "feat: add LLM-powered query suggestion for evaluation sessions

Generates clinician-friendly spaCy Matcher queries from natural
language event descriptions. Supports all LiteLLM providers.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 8: Unified Evaluation Router

**Files:**
- Rewrite: `backend/app/evaluation/router.py`
- Test: `backend/tests/test_eval_router.py`

- [ ] **Step 1: Write failing tests for session CRUD endpoints**

Add to `backend/tests/test_eval_router.py`:

```python
class TestSessionCRUD:
    async def test_create_session(self, auth_client, project_id):
        resp = await auth_client.post(
            f"/api/v1/projects/{project_id}/evaluation/sessions",
            json={"search_queries": [{"query": "troponin", "type": "include"}]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert len(data["search_queries"]) == 1

    async def test_list_sessions(self, auth_client, project_id):
        # Create a session first
        await auth_client.post(
            f"/api/v1/projects/{project_id}/evaluation/sessions",
            json={"search_queries": []},
        )
        resp = await auth_client.get(
            f"/api/v1/projects/{project_id}/evaluation/sessions",
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_get_session(self, auth_client, project_id):
        create_resp = await auth_client.post(
            f"/api/v1/projects/{project_id}/evaluation/sessions",
            json={"search_queries": []},
        )
        session_id = create_resp.json()["id"]

        resp = await auth_client.get(
            f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}",
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == session_id

    async def test_discard_session(self, auth_client, project_id):
        create_resp = await auth_client.post(
            f"/api/v1/projects/{project_id}/evaluation/sessions",
            json={"search_queries": []},
        )
        session_id = create_resp.json()["id"]

        resp = await auth_client.delete(
            f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}",
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "discarded"

    async def test_update_queries(self, auth_client, project_id):
        create_resp = await auth_client.post(
            f"/api/v1/projects/{project_id}/evaluation/sessions",
            json={"search_queries": []},
        )
        session_id = create_resp.json()["id"]

        resp = await auth_client.put(
            f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/queries",
            json={"search_queries": [{"query": "MI OR troponin", "type": "include"}]},
        )
        assert resp.status_code == 200
        assert len(resp.json()["search_queries"]) == 1

    async def test_update_llm_config(self, auth_client, project_id):
        create_resp = await auth_client.post(
            f"/api/v1/projects/{project_id}/evaluation/sessions",
            json={"search_queries": []},
        )
        session_id = create_resp.json()["id"]

        resp = await auth_client.put(
            f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/llm-config",
            json={
                "event_name": "MI",
                "event_description": "Confirmed MI",
                "include_criteria": "Troponin elevation",
                "exclude_criteria": "",
                "llm_provider": "openai",
                "llm_model": "gpt-4o-mini",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["event_name"] == "MI"

    async def test_clone_session(self, auth_client, project_id):
        # Create and discard first session
        create_resp = await auth_client.post(
            f"/api/v1/projects/{project_id}/evaluation/sessions",
            json={"search_queries": [{"query": "troponin", "type": "include"}]},
        )
        old_id = create_resp.json()["id"]
        await auth_client.delete(
            f"/api/v1/projects/{project_id}/evaluation/sessions/{old_id}",
        )

        # Clone from old session
        resp = await auth_client.post(
            f"/api/v1/projects/{project_id}/evaluation/sessions/{old_id}/clone",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["cloned_from_id"] == old_id
        assert data["search_queries"] == [{"query": "troponin", "type": "include"}]


class TestFunnelAndMatches:
    async def test_get_funnel_stats(self, auth_client, project_id):
        create_resp = await auth_client.post(
            f"/api/v1/projects/{project_id}/evaluation/sessions",
            json={"search_queries": []},
        )
        session_id = create_resp.json()["id"]

        resp = await auth_client.get(
            f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/funnel",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sample_patients" in data
        assert "filter_percent" in data


class TestResultsAndJudgment:
    async def test_get_results_empty(self, auth_client, project_id):
        create_resp = await auth_client.post(
            f"/api/v1/projects/{project_id}/evaluation/sessions",
            json={"search_queries": []},
        )
        session_id = create_resp.json()["id"]

        resp = await auth_client.get(
            f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/results",
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_get_metrics_empty(self, auth_client, project_id):
        create_resp = await auth_client.post(
            f"/api/v1/projects/{project_id}/evaluation/sessions",
            json={"search_queries": []},
        )
        session_id = create_resp.json()["id"]

        resp = await auth_client.get(
            f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/metrics",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_reviewed"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_eval_router.py -v -x`
Expected: FAIL (old router doesn't have new endpoints)

- [ ] **Step 3: Write the unified evaluation router**

```python
# backend/app/evaluation/router.py
"""Unified evaluation session API routes.

Replaces: old evaluation router + pipeline EventConfig endpoints.
All endpoints under /api/v1/projects/{project_id}/evaluation/sessions.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.dependencies import require_project_role
from app.evaluation.schemas import (
    CommitRequest,
    CommitResponse,
    CreateSessionRequest,
    FunnelResponse,
    LlmConfigRequest,
    MetricsResponse,
    PipelineStatsResponse,
    QueryMatchesResponse,
    SessionListResponse,
    SessionResponse,
    SubmitJudgmentRequest,
    SuggestQueriesRequest,
    SuggestQueriesResponse,
    UpdateQueriesRequest,
)
from app.evaluation.service import (
    commit_session,
    compute_metrics,
    create_session,
    discard_session,
    execute_search_queries,
    get_funnel_stats,
    get_query_matches,
    get_session as get_eval_session,
    list_patient_results,
    list_sessions,
    run_llm_on_sample,
    submit_judgment,
    update_llm_config,
    update_queries,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/evaluation",
    tags=["evaluation"],
)


# ── Sessions ─────────────────────────────────────────────────────


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session_endpoint(
    project_id: str,
    body: CreateSessionRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    """Create a new evaluation session with patient sampling."""
    try:
        queries = [q.model_dump() for q in body.search_queries]
        eval_session = await create_session(
            session,
            project_id=project_id,
            user_id=current_user.id,
            search_queries=queries,
            cloned_from_id=body.cloned_from_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return eval_session


@router.get("/sessions", response_model=list[SessionListResponse])
async def list_sessions_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    return await list_sessions(session, project_id)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    eval_session = await get_eval_session(session, session_id)
    if not eval_session or eval_session.project_id != project_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return eval_session


@router.delete("/sessions/{session_id}", response_model=SessionResponse)
async def discard_session_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Discard a draft or reviewing session (instant, no confirmation)."""
    try:
        return await discard_session(session, session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/{session_id}/clone", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def clone_session_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    """Clone queries + LLM config from a previous session into a new one."""
    try:
        return await create_session(
            session,
            project_id=project_id,
            user_id=current_user.id,
            search_queries=[],
            cloned_from_id=session_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Search Queries ───────────────────────────────────────────────


@router.put("/sessions/{session_id}/queries", response_model=SessionResponse)
async def update_queries_endpoint(
    project_id: str,
    session_id: str,
    body: UpdateQueriesRequest,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Update the query list and clear old search matches."""
    try:
        queries = [q.model_dump() for q in body.search_queries]
        return await update_queries(session, session_id, queries)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/{session_id}/queries/suggest", response_model=SuggestQueriesResponse)
async def suggest_queries_endpoint(
    project_id: str,
    session_id: str,
    body: SuggestQueriesRequest,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Use LLM to suggest search queries from a natural language description."""
    from app.evaluation.query_suggest import suggest_queries

    try:
        suggestions = await suggest_queries(
            description=body.description,
            llm_provider=body.llm_provider,
            llm_model=body.llm_model,
            llm_api_base=body.llm_api_base,
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return SuggestQueriesResponse(suggestions=suggestions)


@router.post("/sessions/{session_id}/queries/execute", response_model=FunnelResponse)
async def execute_queries_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Run search queries against sample patient notes. Updates SearchMatch records."""
    try:
        await execute_search_queries(session, session_id)
        return await get_funnel_stats(session, session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/sessions/{session_id}/queries/{query_index}/matches",
    response_model=QueryMatchesResponse,
)
async def get_query_matches_endpoint(
    project_id: str,
    session_id: str,
    query_index: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get matched notes for a specific query with highlighted positions."""
    try:
        return await get_query_matches(session, session_id, query_index, page, page_size)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── LLM Classification ──────────────────────────────────────────


@router.put("/sessions/{session_id}/llm-config", response_model=SessionResponse)
async def update_llm_config_endpoint(
    project_id: str,
    session_id: str,
    body: LlmConfigRequest,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Update LLM configuration (event definition + model selection)."""
    try:
        return await update_llm_config(session, session_id, **body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/{session_id}/run-llm")
async def run_llm_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Run LLM classification on all matched sample patients.

    Returns stats: patients_classified, patients_no_match, patients_failed, token_usage.
    """
    try:
        return await run_llm_on_sample(session, session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Results & Review ─────────────────────────────────────────────


@router.get("/sessions/{session_id}/results")
async def list_results_endpoint(
    project_id: str,
    session_id: str,
    label: str | None = Query(default=None),
    reviewed: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """List patient results with optional filtering by label and review status."""
    return await list_patient_results(
        session, session_id, label_filter=label, reviewed_filter=reviewed,
        page=page, page_size=page_size,
    )


@router.post("/sessions/{session_id}/results/{result_id}/judge")
async def submit_judgment_endpoint(
    project_id: str,
    session_id: str,
    result_id: int,
    body: SubmitJudgmentRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin", "annotator")),
):
    """Submit a clinician judgment (correct/wrong/skipped) with optional date override."""
    if body.judgment not in ("correct", "wrong", "skipped"):
        raise HTTPException(status_code=400, detail="Invalid judgment value")
    try:
        pr = await submit_judgment(
            session, result_id, body.judgment, current_user.id,
            event_date_override=body.event_date_override,
        )
        return pr
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/sessions/{session_id}/metrics", response_model=MetricsResponse)
async def metrics_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get live accuracy/precision/recall/F1 metrics from reviewed results."""
    return await compute_metrics(session, session_id)


# ── Funnel Stats ─────────────────────────────────────────────────


@router.get("/sessions/{session_id}/funnel", response_model=FunnelResponse)
async def funnel_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get funnel bar data: sample → search match → LLM positive."""
    try:
        return await get_funnel_stats(session, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Commit & Pipeline ────────────────────────────────────────────


@router.post("/sessions/{session_id}/commit", response_model=CommitResponse)
async def commit_endpoint(
    project_id: str,
    session_id: str,
    body: CommitRequest = CommitRequest(),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    """Commit the session (lock config) and dispatch a full pipeline run."""
    try:
        eval_session = await commit_session(
            session, session_id, current_user.id,
            confidence_threshold=body.confidence_threshold,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Dispatch full pipeline run
    from app.evaluation.service import dispatch_full_pipeline_run

    try:
        run = await dispatch_full_pipeline_run(session, eval_session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return CommitResponse(
        session=eval_session,
        pipeline_run_id=run.id,
        total_patients=run.total_patients,
    )


@router.get("/sessions/{session_id}/pipeline/stats", response_model=PipelineStatsResponse)
async def pipeline_stats_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get full pipeline run progress for a committed session."""
    from app.evaluation.service import get_pipeline_stats

    try:
        return await get_pipeline_stats(session, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/sessions/{session_id}/pipeline/cancel")
async def cancel_pipeline_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Cancel a running full pipeline. Allows new sessions to be created."""
    from app.evaluation.service import cancel_pipeline_run

    try:
        return await cancel_pipeline_run(session, session_id, project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/{session_id}/pipeline/retry-failed")
async def retry_failed_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Retry failed patients in the full pipeline run."""
    from app.evaluation.service import retry_failed_pipeline

    try:
        return await retry_failed_pipeline(session, session_id, project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_eval_router.py -v -x`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/evaluation/router.py tests/test_eval_router.py
git commit -m "feat: rewrite evaluation router with unified session API endpoints

All endpoints under /api/v1/projects/{id}/evaluation/sessions:
- Session CRUD (create, list, get, discard, clone)
- Query management (update, suggest, execute, match preview)
- LLM config + run
- Results, judgment, metrics
- Commit + pipeline (stats, cancel, retry)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 9: Pipeline Dispatch Service Functions + WebSocket

**Files:**
- Modify: `backend/app/evaluation/service.py` (append pipeline dispatch functions)
- Create: `backend/app/evaluation/ws.py`
- Modify: `backend/app/main.py` (register new WebSocket)

- [ ] **Step 1: Add pipeline dispatch functions to service**

Append to `backend/app/evaluation/service.py`:

```python
from app.pipeline.models import PipelineRun, PipelineRunStatus
from app.pipeline.orchestrator import _enqueue_pipeline_run


async def dispatch_full_pipeline_run(
    db: AsyncSession, eval_session: EvaluationSession
) -> PipelineRun:
    """Create a PipelineRun for the committed session and dispatch to workers."""
    # Count all patients in project
    stmt = select(func.count(Patient.id)).where(
        Patient.project_id == eval_session.project_id,
        Patient.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    total_patients = result.scalar() or 0

    run = PipelineRun(
        project_id=eval_session.project_id,
        event_config_id=None,  # New sessions don't use EventConfig
        run_type="full",
        status=PipelineRunStatus.QUEUED,
        config_snapshot=eval_session.committed_config,
        total_patients=total_patients,
        created_by=eval_session.committed_by,
    )
    db.add(run)
    await db.flush()

    # Create PatientResult rows for ALL patients
    stmt = select(Patient.id).where(
        Patient.project_id == eval_session.project_id,
        Patient.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    all_patient_ids = [row[0] for row in result.all()]

    # Copy sample results that are already completed
    sample_result_map = {}
    stmt = select(PatientResult).where(
        PatientResult.session_id == eval_session.id,
        PatientResult.pipeline_run_id.is_(None),
        PatientResult.status.in_([PatientResultStatus.COMPLETED, PatientResultStatus.NO_MATCH]),
    )
    result = await db.execute(stmt)
    for sr in result.scalars().all():
        sample_result_map[sr.patient_id] = sr

    for pid in all_patient_ids:
        if pid in sample_result_map:
            # Copy sample result
            sr = sample_result_map[pid]
            pr = PatientResult(
                session_id=eval_session.id,
                pipeline_run_id=run.id,
                patient_id=pid,
                status=sr.status,
                notes_searched=sr.notes_searched,
                notes_matched=sr.notes_matched,
                finding_label=sr.finding_label,
                finding_reasoning=sr.finding_reasoning,
                finding_evidence=sr.finding_evidence,
                event_date=sr.event_date,
                predicted_score=sr.predicted_score,
                token_usage=sr.token_usage,
                completed_at=sr.completed_at,
            )
        else:
            pr = PatientResult(
                session_id=eval_session.id,
                pipeline_run_id=run.id,
                patient_id=pid,
                status=PatientResultStatus.QUEUED,
            )
        db.add(pr)

    await db.commit()
    await db.refresh(run)
    await _enqueue_pipeline_run(run.id)
    return run


async def get_pipeline_stats(db: AsyncSession, session_id: str) -> dict:
    """Get pipeline run stats for a committed session."""
    session = await db.get(EvaluationSession, session_id)
    if not session or session.status not in (SessionStatus.COMMITTED, SessionStatus.COMPLETED):
        raise ValueError("No committed pipeline for this session")

    # Find the pipeline run
    stmt = select(PipelineRun).where(
        PipelineRun.config_snapshot.isnot(None),
    ).order_by(PipelineRun.created_at.desc())
    result = await db.execute(stmt)
    run = None
    for r in result.scalars().all():
        # Match by checking PatientResult linkage
        check_stmt = select(func.count(PatientResult.id)).where(
            PatientResult.session_id == session_id,
            PatientResult.pipeline_run_id == r.id,
        )
        check_result = await db.execute(check_stmt)
        if (check_result.scalar() or 0) > 0:
            run = r
            break

    if not run:
        raise ValueError("Pipeline run not found for this session")

    # Aggregate PatientResult statuses
    stmt = (
        select(PatientResult.status, func.count())
        .where(
            PatientResult.session_id == session_id,
            PatientResult.pipeline_run_id == run.id,
        )
        .group_by(PatientResult.status)
    )
    result = await db.execute(stmt)
    counts = {s.value: c for s, c in result.all()}

    return {
        "total": sum(counts.values()),
        "queued": counts.get("queued", 0),
        "processing": counts.get("processing", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "no_match": counts.get("no_match", 0),
        "is_cancelled": run.is_cancelled,
    }


async def cancel_pipeline_run(db: AsyncSession, session_id: str, project_id: str) -> dict:
    """Cancel the pipeline run for a committed session."""
    from app.pipeline.orchestrator import cancel_run

    session = await db.get(EvaluationSession, session_id)
    if not session:
        raise ValueError("Session not found")

    # Find associated pipeline run
    stmt = select(PatientResult.pipeline_run_id).where(
        PatientResult.session_id == session_id,
        PatientResult.pipeline_run_id.isnot(None),
    ).distinct().limit(1)
    result = await db.execute(stmt)
    row = result.first()
    if not row:
        raise ValueError("No pipeline run found for this session")

    run = await cancel_run(db, project_id, row[0])
    if not run:
        raise ValueError("Pipeline run not found")

    # Allow new sessions by moving committed session to discarded
    session.status = SessionStatus.DISCARDED
    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()

    return {"status": "cancelled", "run_id": run.id}


async def retry_failed_pipeline(db: AsyncSession, session_id: str, project_id: str) -> dict:
    """Retry failed patients in the full pipeline run."""
    stmt = select(PatientResult.pipeline_run_id).where(
        PatientResult.session_id == session_id,
        PatientResult.pipeline_run_id.isnot(None),
    ).distinct().limit(1)
    result = await db.execute(stmt)
    row = result.first()
    if not row:
        raise ValueError("No pipeline run found for this session")

    # Reset failed PatientResults to queued
    stmt = select(PatientResult).where(
        PatientResult.session_id == session_id,
        PatientResult.pipeline_run_id == row[0],
        PatientResult.status == PatientResultStatus.FAILED,
    )
    result = await db.execute(stmt)
    failed = list(result.scalars().all())

    if not failed:
        raise ValueError("No failed patients to retry")

    for pr in failed:
        pr.status = PatientResultStatus.QUEUED
        pr.error_message = None
        pr.started_at = None
        pr.completed_at = None
        db.add(pr)

    await db.commit()
    await _enqueue_pipeline_run(row[0])
    return {"requeued": len(failed), "run_id": row[0]}
```

- [ ] **Step 2: Write the WebSocket for LLM progress**

```python
# backend/app/evaluation/ws.py
"""WebSocket endpoint for real-time pipeline progress on evaluation sessions."""

import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect

from app.common.database import async_session
from app.evaluation.models import EvaluationSession, SessionStatus

logger = logging.getLogger(__name__)


async def eval_pipeline_progress_ws(websocket: WebSocket, project_id: str, session_id: str):
    """Stream full pipeline run progress for a committed evaluation session.

    Polls PatientResult aggregate counts every 1s and pushes updates.
    Closes when the session reaches COMPLETED state.
    """
    await websocket.accept()
    last_stats: dict = {}

    try:
        while True:
            async with async_session() as db:
                eval_sess = await db.get(EvaluationSession, session_id)
                if not eval_sess or eval_sess.project_id != project_id:
                    await websocket.send_json({"type": "error", "detail": "Session not found"})
                    break

                if eval_sess.status not in (SessionStatus.COMMITTED, SessionStatus.COMPLETED):
                    await websocket.send_json({
                        "type": "status",
                        "session_status": eval_sess.status.value,
                    })
                    break

                from app.evaluation.service import get_pipeline_stats

                try:
                    stats = await get_pipeline_stats(db, session_id)
                except ValueError:
                    await websocket.send_json({"type": "error", "detail": "No pipeline run found"})
                    break

            msg = {"type": "progress", "session_id": session_id, **stats}

            if stats != last_stats:
                last_stats = stats
                await websocket.send_json(msg)

            # Check if done
            if stats.get("queued", 0) == 0 and stats.get("processing", 0) == 0:
                msg["type"] = "completed"
                await websocket.send_json(msg)
                break

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
```

- [ ] **Step 3: Register WebSocket in main.py**

In `backend/app/main.py`, add after line 88:

```python
    from app.evaluation.ws import eval_pipeline_progress_ws

    application.websocket("/ws/projects/{project_id}/evaluation/{session_id}")(eval_pipeline_progress_ws)
```

- [ ] **Step 4: Run full router tests**

Run: `cd backend && uv run pytest tests/test_eval_router.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/evaluation/service.py app/evaluation/ws.py app/main.py
git commit -m "feat: add pipeline dispatch, stats, cancel, retry + WebSocket for eval sessions

dispatch_full_pipeline_run creates PipelineRun + PatientResult rows
for all project patients, copies sample results. WebSocket streams
progress via polling. Registered at /ws/projects/{id}/evaluation/{sid}.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```
