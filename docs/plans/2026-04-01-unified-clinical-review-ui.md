# Unified Clinical Review UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the eval ResultsSection card-list with an annotation-style two-column review UI that shows one patient at a time with full note context, LLM evidence, and clinician judgment actions.

**Architecture:** Add two new backend endpoints (next-unreviewed patient, full note context for a result). Create a new `EvalReviewPanel` frontend component that mirrors the annotation `PatientReviewPanel` layout — left panel for patient info + LLM prediction + actions, right panel for evidence notes with full text. The existing `ResultsSection` becomes a summary bar; the rich review happens in the new panel.

**Tech Stack:** FastAPI (backend), React + TypeScript + TanStack Query (frontend), SQLAlchemy async (ORM), shadcn/ui components.

---

## File Structure

### Backend
- **Modify:** `backend/app/evaluation/service.py` — add `get_next_unreviewed_result()`, `get_result_note_context()`
- **Modify:** `backend/app/evaluation/router.py` — add two new endpoints
- **Modify:** `backend/app/evaluation/schemas.py` — add response schemas
- **Test:** `backend/tests/test_eval_review.py` — new test file for review endpoints

### Frontend
- **Create:** `frontend/src/projects/evaluation/EvalReviewPanel.tsx` — two-column review UI
- **Create:** `frontend/src/projects/evaluation/EvalNoteViewer.tsx` — note viewer adapted for evidence
- **Modify:** `frontend/src/projects/evaluation/ResultsSection.tsx` — add toggle for review mode
- **Modify:** `frontend/src/projects/evaluation/EvaluationSessionPage.tsx` — wire up review panel
- **Modify:** `frontend/src/projects/types.ts` — add new types

---

## Task 1: Backend — Next Unreviewed Result Endpoint

**Files:**
- Modify: `backend/app/evaluation/service.py`
- Modify: `backend/app/evaluation/router.py`
- Modify: `backend/app/evaluation/schemas.py`
- Test: `backend/tests/test_eval_review.py`

- [ ] **Step 1: Write failing test for `get_next_unreviewed_result`**

Create `backend/tests/test_eval_review.py`:

```python
"""Tests for sequential evaluation review endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _register_and_login(client: AsyncClient) -> dict:
    await client.post("/api/v1/auth/register", json={
        "email": "reviewer@test.com", "password": "testpass123", "name": "Reviewer"
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "reviewer@test.com", "password": "testpass123"
    })
    return resp.json()


async def _create_project(client: AsyncClient) -> str:
    resp = await client.post("/api/v1/projects/", json={
        "name": "Review Test", "description": "test"
    })
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_next_unreviewed_returns_404_when_no_results(client):
    await _register_and_login(client)
    project_id = await _create_project(client)

    # Create a session
    resp = await client.post(
        f"/api/v1/projects/{project_id}/evaluation/sessions",
        json={"search_queries": [{"query": "stroke", "type": "include"}]},
    )
    session_id = resp.json()["id"]

    # No results exist yet — should 404
    resp = await client.get(
        f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/results/next"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_next_unreviewed_returns_result(client):
    """Full flow: create session, add patient result, get next unreviewed."""
    await _register_and_login(client)
    project_id = await _create_project(client)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/evaluation/sessions",
        json={"search_queries": [{"query": "stroke", "type": "include"}]},
    )
    session_id = resp.json()["id"]

    # Manually insert a patient result via the DB
    from app.common.database import get_session as get_db
    from app.evaluation.models import PatientResult, PatientResultStatus

    async for db in get_db():
        pr = PatientResult(
            session_id=session_id,
            patient_id="fake-patient-1",
            status=PatientResultStatus.COMPLETED,
            finding_label="positive",
            finding_reasoning="Test reasoning",
            predicted_score=0.9,
        )
        db.add(pr)
        await db.commit()

    resp = await client.get(
        f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/results/next"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["patient_id"] == "fake-patient-1"
    assert data["finding_label"] == "positive"
    assert data["review_judgment"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_eval_review.py -v -x`
Expected: FAIL — endpoint `/results/next` doesn't exist (404 from router, not from our logic).

- [ ] **Step 3: Add schema for next-result response**

In `backend/app/evaluation/schemas.py`, add after `PatientResultResponse`:

```python
class NextResultResponse(BaseModel):
    id: int
    patient_id: str
    status: str
    finding_label: str | None
    finding_reasoning: str | None
    finding_evidence: list[dict] | None
    event_date: str | None
    predicted_score: float | None
    review_judgment: str | None
    reviewer_date_override: str | None
    notes_searched: int
    notes_matched: int
    # Navigation context
    position: int  # 1-based index in unreviewed queue
    total_unreviewed: int
    total_results: int
```

- [ ] **Step 4: Implement `get_next_unreviewed_result` in service**

In `backend/app/evaluation/service.py`, add:

```python
async def get_next_unreviewed_result(
    db: AsyncSession,
    session_id: str,
    after_id: int | None = None,
) -> dict | None:
    """Get the next unreviewed patient result for sequential review.

    Returns the result plus navigation context (position, totals).
    If after_id is provided, returns the next unreviewed after that ID.
    """
    # Count totals
    total_stmt = select(func.count()).where(
        PatientResult.session_id == session_id,
        PatientResult.status == PatientResultStatus.COMPLETED,
    )
    total_results = (await db.execute(total_stmt)).scalar() or 0

    unreviewed_stmt = select(func.count()).where(
        PatientResult.session_id == session_id,
        PatientResult.status == PatientResultStatus.COMPLETED,
        PatientResult.review_judgment.is_(None),
    )
    total_unreviewed = (await db.execute(unreviewed_stmt)).scalar() or 0

    if total_unreviewed == 0:
        return None

    # Get next unreviewed, ordered by predicted_score desc (highest confidence first)
    next_stmt = (
        select(PatientResult)
        .where(
            PatientResult.session_id == session_id,
            PatientResult.status == PatientResultStatus.COMPLETED,
            PatientResult.review_judgment.is_(None),
        )
        .order_by(PatientResult.predicted_score.desc().nullslast(), PatientResult.id)
    )
    if after_id is not None:
        next_stmt = next_stmt.where(PatientResult.id > after_id)

    next_stmt = next_stmt.limit(1)
    result = (await db.execute(next_stmt)).scalar_one_or_none()

    # If after_id caused us to miss results, wrap around
    if result is None and after_id is not None:
        next_stmt = (
            select(PatientResult)
            .where(
                PatientResult.session_id == session_id,
                PatientResult.status == PatientResultStatus.COMPLETED,
                PatientResult.review_judgment.is_(None),
            )
            .order_by(PatientResult.predicted_score.desc().nullslast(), PatientResult.id)
            .limit(1)
        )
        result = (await db.execute(next_stmt)).scalar_one_or_none()

    if result is None:
        return None

    position = total_results - total_unreviewed + 1

    return {
        "id": result.id,
        "patient_id": result.patient_id,
        "status": result.status.value if hasattr(result.status, "value") else result.status,
        "finding_label": result.finding_label,
        "finding_reasoning": result.finding_reasoning,
        "finding_evidence": result.finding_evidence,
        "event_date": result.event_date,
        "predicted_score": result.predicted_score,
        "review_judgment": result.review_judgment,
        "reviewer_date_override": result.reviewer_date_override,
        "notes_searched": result.notes_searched,
        "notes_matched": result.notes_matched,
        "position": position,
        "total_unreviewed": total_unreviewed,
        "total_results": total_results,
    }
```

- [ ] **Step 5: Add router endpoint**

In `backend/app/evaluation/router.py`, add before the existing `list_results_endpoint`:

```python
from app.evaluation.schemas import NextResultResponse
from app.evaluation.service import get_next_unreviewed_result

@router.get("/sessions/{session_id}/results/next", response_model=NextResultResponse)
async def next_unreviewed_endpoint(
    project_id: str,
    session_id: str,
    after_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator")),
):
    """Get the next unreviewed patient result for sequential review."""
    await _get_session_or_404(db, project_id, session_id)
    result = await get_next_unreviewed_result(db, session_id, after_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No unreviewed results")
    return result
```

**Important:** This endpoint MUST be registered before the `"/sessions/{session_id}/results/{result_id}/judge"` route, otherwise FastAPI will try to parse "next" as a `result_id` integer and fail.

- [ ] **Step 6: Add import to router**

In the import block at the top of `backend/app/evaluation/router.py`, add `NextResultResponse` to the schemas import and `get_next_unreviewed_result` to the service import.

- [ ] **Step 7: Run tests**

Run: `cd backend && uv run pytest tests/test_eval_review.py -v -x`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/evaluation/service.py backend/app/evaluation/router.py backend/app/evaluation/schemas.py backend/tests/test_eval_review.py
git commit -m "feat: add next-unreviewed-result endpoint for sequential eval review"
```

---

## Task 2: Backend — Note Context for Patient Result

**Files:**
- Modify: `backend/app/evaluation/service.py`
- Modify: `backend/app/evaluation/router.py`
- Modify: `backend/app/evaluation/schemas.py`
- Test: `backend/tests/test_eval_review.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_eval_review.py`:

```python
@pytest.mark.asyncio
async def test_result_notes_returns_full_context(client):
    """Notes endpoint returns full note text for evidence review."""
    await _register_and_login(client)
    project_id = await _create_project(client)

    # Create session
    resp = await client.post(
        f"/api/v1/projects/{project_id}/evaluation/sessions",
        json={"search_queries": [{"query": "stroke", "type": "include"}]},
    )
    session_id = resp.json()["id"]

    # Insert patient + note + search match + patient result via DB
    from app.common.database import get_session as get_db
    from app.connectors.models import Patient, Note
    from app.evaluation.models import PatientResult, PatientResultStatus, SearchMatch
    from datetime import datetime, UTC

    async for db in get_db():
        patient = Patient(project_id=project_id, patient_id_ext="MRN001")
        db.add(patient)
        await db.flush()

        note = Note(
            project_id=project_id,
            patient_id=patient.id,
            text_id="NOTE001",
            note_date=datetime(2026, 1, 15, tzinfo=UTC),
            text="Patient presented with acute ischemic stroke symptoms.",
        )
        db.add(note)
        await db.flush()

        sm = SearchMatch(
            session_id=session_id,
            patient_id=patient.id,
            note_id=note.id,
            matched_tokens=["stroke"],
            match_positions=[{"start": 40, "end": 46, "token": "stroke"}],
        )
        db.add(sm)

        pr = PatientResult(
            session_id=session_id,
            patient_id=patient.id,
            status=PatientResultStatus.COMPLETED,
            finding_label="positive",
            finding_reasoning="Acute stroke confirmed",
            finding_evidence=[{
                "note_id": note.id,
                "text": "acute ischemic stroke symptoms",
                "note_date": "2026-01-15",
            }],
            predicted_score=0.95,
            notes_searched=1,
            notes_matched=1,
        )
        db.add(pr)
        await db.commit()

        result_id = pr.id

    resp = await client.get(
        f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/results/{result_id}/notes"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["notes"]) == 1
    assert data["notes"][0]["text_id"] == "NOTE001"
    assert "stroke" in data["notes"][0]["text"]
    assert len(data["notes"][0]["matched_tokens"]) > 0
    assert data["search_keywords"] == ["stroke"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_eval_review.py::test_result_notes_returns_full_context -v -x`
Expected: FAIL — endpoint doesn't exist.

- [ ] **Step 3: Add response schema**

In `backend/app/evaluation/schemas.py`, add:

```python
class ResultNoteContext(BaseModel):
    note_id: str
    text_id: str
    text: str
    note_date: str | None
    note_tags: dict
    matched_tokens: list[str]
    match_positions: list[dict]
    is_evidence: bool  # True if this note is in the LLM's evidence list


class ResultNotesResponse(BaseModel):
    patient_id: str
    patient_id_ext: str | None
    notes: list[ResultNoteContext]
    search_keywords: list[str]
```

- [ ] **Step 4: Implement `get_result_note_context` in service**

In `backend/app/evaluation/service.py`, add:

```python
async def get_result_note_context(
    db: AsyncSession,
    session_id: str,
    result_id: int,
) -> dict | None:
    """Get full note context for a patient result, including search matches.

    Returns all matched notes for the patient with:
    - Full note text
    - Search match highlights (tokens + positions)
    - Whether each note is cited in the LLM's evidence
    """
    pr = (
        await db.execute(
            select(PatientResult).where(
                PatientResult.id == result_id,
                PatientResult.session_id == session_id,
            )
        )
    ).scalar_one_or_none()
    if not pr:
        return None

    # Get the patient's external ID
    patient = (
        await db.execute(select(Patient).where(Patient.id == pr.patient_id))
    ).scalar_one_or_none()

    # Get search queries for keywords
    eval_session = await db.get(EvaluationSession, session_id)
    search_keywords = []
    if eval_session and eval_session.search_queries:
        for q in eval_session.search_queries:
            if isinstance(q, dict) and q.get("type") != "exclude":
                search_keywords.append(q["query"])

    # Get all SearchMatch rows for this patient in this session
    matches_stmt = (
        select(SearchMatch)
        .where(
            SearchMatch.session_id == session_id,
            SearchMatch.patient_id == pr.patient_id,
        )
    )
    matches_result = await db.execute(matches_stmt)
    search_matches = matches_result.scalars().all()

    # Group matches by note_id
    matches_by_note: dict[str, list] = {}
    for m in search_matches:
        matches_by_note.setdefault(m.note_id, []).append(m)

    # Build evidence note_id set for marking
    evidence_note_ids = set()
    if pr.finding_evidence:
        for ev in pr.finding_evidence:
            if isinstance(ev, dict) and "note_id" in ev:
                evidence_note_ids.add(ev["note_id"])

    # Fetch full notes
    note_ids = list(matches_by_note.keys())
    if not note_ids:
        return {
            "patient_id": pr.patient_id,
            "patient_id_ext": patient.patient_id_ext if patient else None,
            "notes": [],
            "search_keywords": search_keywords,
        }

    notes_stmt = (
        select(Note)
        .where(Note.id.in_(note_ids))
        .order_by(Note.note_date)
    )
    notes_result = await db.execute(notes_stmt)
    notes = notes_result.scalars().all()

    note_contexts = []
    for note in notes:
        note_matches = matches_by_note.get(note.id, [])
        all_tokens = []
        all_positions = []
        for m in note_matches:
            all_tokens.extend(m.matched_tokens or [])
            all_positions.extend(m.match_positions or [])

        note_contexts.append({
            "note_id": note.id,
            "text_id": note.text_id,
            "text": note.text,
            "note_date": note.note_date.isoformat() if note.note_date else None,
            "note_tags": note.metadata_ or {},
            "matched_tokens": list(set(all_tokens)),
            "match_positions": all_positions,
            "is_evidence": note.id in evidence_note_ids,
        })

    return {
        "patient_id": pr.patient_id,
        "patient_id_ext": patient.patient_id_ext if patient else None,
        "notes": note_contexts,
        "search_keywords": search_keywords,
    }
```

Add necessary imports at the top of service.py:
```python
from app.connectors.models import Patient, Note
```

(Check if `Patient` and `Note` are already imported — `Patient` is, `Note` may not be.)

- [ ] **Step 5: Add router endpoint**

In `backend/app/evaluation/router.py`, add before the judge endpoint:

```python
from app.evaluation.schemas import ResultNotesResponse
from app.evaluation.service import get_result_note_context

@router.get("/sessions/{session_id}/results/{result_id}/notes", response_model=ResultNotesResponse)
async def result_notes_endpoint(
    project_id: str,
    session_id: str,
    result_id: int,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get full note context for a patient result (for clinical review)."""
    await _get_session_or_404(db, project_id, session_id)
    context = await get_result_note_context(db, session_id, result_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return context
```

- [ ] **Step 6: Add imports to router and service files**

Update imports in `router.py` to include `ResultNotesResponse` and `get_result_note_context`.

Update imports in `service.py` to include `Note` from `app.connectors.models` if not already present.

- [ ] **Step 7: Run tests**

Run: `cd backend && uv run pytest tests/test_eval_review.py -v -x`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/evaluation/service.py backend/app/evaluation/router.py backend/app/evaluation/schemas.py backend/tests/test_eval_review.py
git commit -m "feat: add note context endpoint for evaluation review"
```

---

## Task 3: Frontend — Types and API

**Files:**
- Modify: `frontend/src/projects/types.ts`

- [ ] **Step 1: Add TypeScript types**

In `frontend/src/projects/types.ts`, add:

```typescript
export interface NextEvalResult {
  id: number;
  patient_id: string;
  status: string;
  finding_label: string | null;
  finding_reasoning: string | null;
  finding_evidence: { note_id: string; text: string; note_date: string }[] | null;
  event_date: string | null;
  predicted_score: number | null;
  review_judgment: string | null;
  reviewer_date_override: string | null;
  notes_searched: number;
  notes_matched: number;
  position: number;
  total_unreviewed: number;
  total_results: number;
}

export interface ResultNoteContext {
  note_id: string;
  text_id: string;
  text: string;
  note_date: string | null;
  note_tags: Record<string, string>;
  matched_tokens: string[];
  match_positions: MatchPosition[];
  is_evidence: boolean;
}

export interface ResultNotesContext {
  patient_id: string;
  patient_id_ext: string | null;
  notes: ResultNoteContext[];
  search_keywords: string[];
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/projects/types.ts
git commit -m "feat: add types for eval review panel"
```

---

## Task 4: Frontend — EvalNoteViewer Component

**Files:**
- Create: `frontend/src/projects/evaluation/EvalNoteViewer.tsx`

This component displays a single clinical note with keyword highlighting and evidence marking, reusing the same visual style as the annotation `NoteViewer`.

- [ ] **Step 1: Create EvalNoteViewer**

```tsx
import { useEffect, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import type { ResultNoteContext } from "@/projects/types";

function highlightKeywords(
  text: string,
  keywords: string[]
): React.ReactNode {
  if (!keywords || keywords.length === 0) return text;
  const escaped = keywords.map((k) =>
    k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  );
  const pattern = new RegExp(`(${escaped.join("|")})`, "gi");
  const parts = text.split(pattern);
  const lowerKeywords = keywords.map((k) => k.toLowerCase());
  return parts.map((part, i) =>
    lowerKeywords.some((k) => part.toLowerCase().startsWith(k)) ? (
      <mark
        key={i}
        className="rounded-sm bg-amber-200/70 px-0.5 text-amber-950 dark:bg-amber-500/30 dark:text-amber-100"
      >
        {part}
      </mark>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "Unknown";
  return new Date(dateStr).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function EvalNoteViewer({
  notes,
  keywords,
  activeNoteId,
}: {
  notes: ResultNoteContext[];
  keywords: string[];
  activeNoteId?: string | null;
}) {
  const activeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [activeNoteId]);

  const noteFont = { fontFamily: "Georgia, 'Times New Roman', serif" };

  if (notes.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No matched notes available for this patient.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {notes.map((note) => {
        const isActive = note.note_id === activeNoteId;
        return (
          <div
            key={note.note_id}
            ref={isActive ? activeRef : undefined}
            className={`rounded-lg border ${
              note.is_evidence
                ? "border-primary/40 bg-primary/5"
                : "border-border"
            } ${isActive ? "ring-2 ring-primary/50" : ""}`}
          >
            <div className="flex items-center gap-2 border-b border-border/50 px-4 py-2">
              <span className="text-xs font-medium text-foreground">
                {note.text_id}
              </span>
              <span className="text-xs text-muted-foreground">
                {formatDate(note.note_date)}
              </span>
              {note.is_evidence && (
                <Badge className="bg-primary/20 text-primary text-[10px] px-1.5 py-0">
                  LLM Evidence
                </Badge>
              )}
              {note.note_tags &&
                Object.entries(note.note_tags)
                  .filter(([k]) => k.startsWith("text_tag"))
                  .map(([key, val]) => (
                    <Badge
                      key={key}
                      variant="outline"
                      className="border-blue-500/30 bg-blue-500/10 px-1.5 py-0 text-[10px] font-normal text-blue-600 dark:text-blue-400"
                    >
                      {String(val)}
                    </Badge>
                  ))}
            </div>
            <div
              className="max-h-64 overflow-y-auto px-4 py-3 text-[14px] leading-relaxed text-foreground/70"
              style={noteFont}
            >
              {highlightKeywords(note.text, keywords)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/projects/evaluation/EvalNoteViewer.tsx
git commit -m "feat: add EvalNoteViewer component for clinical review"
```

---

## Task 5: Frontend — EvalReviewPanel Component

**Files:**
- Create: `frontend/src/projects/evaluation/EvalReviewPanel.tsx`

This is the main review component — mirrors annotation `PatientReviewPanel` layout with eval-specific data and actions.

- [ ] **Step 1: Create EvalReviewPanel**

```tsx
import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  User,
  Check,
  X,
  SkipForward,
  CalendarDays,
  HelpCircle,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { NextEvalResult, ResultNotesContext } from "@/projects/types";
import EvalNoteViewer from "./EvalNoteViewer";

function formatScore(score: number | null): string {
  if (score === null) return "--";
  return (score * 100).toFixed(0) + "%";
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "Unknown";
  return new Date(dateStr).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const LABEL_COLORS: Record<string, string> = {
  positive:
    "bg-emerald-600 text-white hover:bg-emerald-700",
  negative:
    "bg-zinc-500 text-white hover:bg-zinc-600",
  inconclusive:
    "bg-amber-500 text-white hover:bg-amber-600",
};

function ShortcutsOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="w-80 rounded-lg border border-border bg-card p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h4 className="text-sm font-semibold text-foreground">
            Keyboard Shortcuts
          </h4>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-1.5 text-sm">
          {[
            ["C", "Correct (agree with LLM)"],
            ["W", "Wrong (disagree with LLM)"],
            ["S", "Skip"],
            ["E", "Toggle event date override"],
            ["?", "Toggle this help"],
          ].map(([key, desc]) => (
            <div key={key} className="flex items-center justify-between">
              <span className="text-muted-foreground">{desc}</span>
              <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-xs">
                {key}
              </kbd>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function EvalReviewPanel({
  projectId,
  sessionId,
  onRefresh,
}: {
  projectId: string;
  sessionId: string;
  onRefresh: () => void;
}) {
  const queryClient = useQueryClient();
  const [afterId, setAfterId] = useState<number | null>(null);
  const [showDateOverride, setShowDateOverride] = useState(false);
  const [dateValue, setDateValue] = useState("");
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [completionMessage, setCompletionMessage] = useState<string | null>(null);

  // Fetch next unreviewed result
  const {
    data: current,
    isLoading,
    refetch,
  } = useQuery<NextEvalResult>({
    queryKey: ["eval-next-result", projectId, sessionId, afterId],
    queryFn: () => {
      const params = afterId != null ? `?after_id=${afterId}` : "";
      return api.get<NextEvalResult>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/results/next${params}`
      );
    },
    retry: false,
  });

  // Fetch full note context for current result
  const { data: noteContext, isLoading: notesLoading } = useQuery<ResultNotesContext>({
    queryKey: ["eval-result-notes", projectId, sessionId, current?.id],
    queryFn: () =>
      api.get<ResultNotesContext>(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/results/${current!.id}/notes`
      ),
    enabled: !!current,
  });

  // Pre-fill event date from LLM when showing override
  useEffect(() => {
    if (showDateOverride && !dateValue && current?.event_date) {
      setDateValue(current.event_date.slice(0, 10));
    }
  }, [showDateOverride, current?.event_date]); // eslint-disable-line react-hooks/exhaustive-deps

  // Submit judgment
  const judgeMutation = useMutation({
    mutationFn: ({
      judgment,
      event_date_override,
    }: {
      judgment: string;
      event_date_override?: string | null;
    }) =>
      api.post(
        `/projects/${projectId}/evaluation/sessions/${sessionId}/results/${current!.id}/judge`,
        { judgment, event_date_override: event_date_override ?? null }
      ),
    onSuccess: () => {
      setShowDateOverride(false);
      setDateValue("");

      // Invalidate metrics and results
      queryClient.invalidateQueries({
        queryKey: ["eval-metrics", projectId, sessionId],
      });
      queryClient.invalidateQueries({
        queryKey: ["eval-results", projectId, sessionId],
      });
      onRefresh();

      // Check if this was the last one
      if (current && current.total_unreviewed <= 1) {
        setCompletionMessage(
          `All ${current.total_results} patients reviewed!`
        );
        setTimeout(() => setCompletionMessage(null), 3000);
      } else {
        // Advance to next
        setAfterId(current!.id);
        refetch();
      }
    },
  });

  const handleJudge = useCallback(
    (judgment: string) => {
      if (!current || judgeMutation.isPending) return;
      const event_date_override =
        showDateOverride && dateValue ? dateValue : null;
      judgeMutation.mutate({ judgment, event_date_override });
    },
    [current, judgeMutation, showDateOverride, dateValue]
  );

  // Keyboard shortcuts
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      )
        return;

      switch (e.key.toLowerCase()) {
        case "c":
          e.preventDefault();
          handleJudge("correct");
          break;
        case "w":
          e.preventDefault();
          handleJudge("wrong");
          break;
        case "s":
          e.preventDefault();
          handleJudge("skipped");
          break;
        case "e":
          e.preventDefault();
          setShowDateOverride((v) => !v);
          break;
        case "?":
          e.preventDefault();
          setShowShortcuts((v) => !v);
          break;
      }
    }

    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [handleJudge]);

  // Completion state
  if (completionMessage) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border-2 border-emerald-300 bg-emerald-50/50 py-16 dark:border-emerald-700 dark:bg-emerald-950/20">
        <Check className="mb-3 h-10 w-10 text-emerald-500" />
        <p className="text-lg font-medium text-foreground">{completionMessage}</p>
      </div>
    );
  }

  // Loading
  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-full" />
        <div className="grid grid-cols-3 gap-6">
          <Skeleton className="h-64" />
          <Skeleton className="col-span-2 h-64" />
        </div>
      </div>
    );
  }

  // No results to review
  if (!current) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border-2 border-emerald-300 bg-emerald-50/50 py-16 dark:border-emerald-700 dark:bg-emerald-950/20">
        <Check className="mb-3 h-10 w-10 text-emerald-500" />
        <p className="text-lg font-medium text-foreground">
          All patients reviewed
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Check the metrics panel to see evaluation results.
        </p>
      </div>
    );
  }

  const isPending = judgeMutation.isPending;
  const progressPct =
    current.total_results > 0
      ? Math.round(
          ((current.total_results - current.total_unreviewed) /
            current.total_results) *
            100
        )
      : 0;

  return (
    <TooltipProvider delayDuration={200}>
      <div className="space-y-4">
        {showShortcuts && (
          <ShortcutsOverlay onClose={() => setShowShortcuts(false)} />
        )}

        {/* Top bar */}
        <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/30 px-4 py-2.5">
          <span className="text-sm font-medium tabular-nums text-foreground">
            {current.total_results - current.total_unreviewed + 1} of{" "}
            {current.total_results}
          </span>
          <div className="mx-2 h-5 w-px bg-border" />
          <div className="flex-1">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-emerald-500 transition-all duration-300"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
          <span className="text-xs tabular-nums text-muted-foreground">
            {current.total_unreviewed} remaining
          </span>
          <div className="mx-1 h-5 w-px bg-border" />
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => setShowShortcuts((v) => !v)}
              >
                <HelpCircle className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Keyboard shortcuts (?)</TooltipContent>
          </Tooltip>
        </div>

        {/* Two-column layout */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[340px_1fr]">
          {/* LEFT PANEL */}
          <div className="space-y-4">
            {/* Patient card */}
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <User className="h-4 w-4" />
                Patient
              </div>
              <div className="font-mono text-lg font-semibold text-foreground">
                {noteContext?.patient_id_ext ?? current.patient_id.slice(0, 8)}
              </div>
              <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
                <span>{current.notes_searched} notes searched</span>
                <span>&middot;</span>
                <span>{current.notes_matched} matched</span>
              </div>
            </div>

            {/* AI Prediction card */}
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <Brain className="h-4 w-4" />
                LLM Classification
              </div>

              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  {current.finding_label && (
                    <Badge
                      className={
                        LABEL_COLORS[current.finding_label] ?? "bg-zinc-500 text-white"
                      }
                    >
                      {current.finding_label === "positive"
                        ? "Event Detected"
                        : current.finding_label === "negative"
                          ? "No Event"
                          : "Inconclusive"}
                    </Badge>
                  )}
                  <span className="text-sm tabular-nums text-muted-foreground">
                    {formatScore(current.predicted_score)} confidence
                  </span>
                </div>

                {current.event_date && (
                  <div className="flex items-center gap-2 text-sm">
                    <CalendarDays className="h-4 w-4 text-rose-500" />
                    <span className="text-foreground/80">
                      Event: {formatDate(current.event_date)}
                    </span>
                  </div>
                )}

                {current.finding_reasoning && (
                  <div className="rounded-md bg-muted/50 p-3">
                    <div className="mb-1 text-xs font-medium text-muted-foreground">
                      Reasoning
                    </div>
                    <p className="text-sm leading-relaxed text-foreground/80">
                      {current.finding_reasoning}
                    </p>
                  </div>
                )}

                {/* Evidence summary */}
                {current.finding_evidence && current.finding_evidence.length > 0 && (
                  <div className="text-xs text-muted-foreground">
                    {current.finding_evidence.length} evidence note
                    {current.finding_evidence.length !== 1 ? "s" : ""} cited
                  </div>
                )}
              </div>
            </div>

            {/* Actions */}
            <div className="space-y-2">
              <Button
                onClick={() => handleJudge("correct")}
                disabled={isPending}
                className="w-full gap-2 bg-emerald-600 hover:bg-emerald-700"
                size="lg"
              >
                <Check className="h-4 w-4" />
                Correct
                <kbd className="ml-auto rounded border border-white/20 bg-white/10 px-1.5 py-0.5 text-xs">
                  C
                </kbd>
              </Button>

              <Button
                onClick={() => handleJudge("wrong")}
                disabled={isPending}
                variant="destructive"
                className="w-full gap-2"
                size="lg"
              >
                <X className="h-4 w-4" />
                Wrong
                <kbd className="ml-auto rounded border border-white/20 bg-white/10 px-1.5 py-0.5 text-xs">
                  W
                </kbd>
              </Button>

              <Button
                onClick={() => handleJudge("skipped")}
                disabled={isPending}
                variant="outline"
                className="w-full gap-2"
                size="lg"
              >
                <SkipForward className="h-4 w-4" />
                Skip
                <kbd className="ml-auto rounded border border-border bg-muted px-1.5 py-0.5 text-xs">
                  S
                </kbd>
              </Button>

              {/* Event date override */}
              {!showDateOverride ? (
                <Button
                  variant="outline"
                  onClick={() => setShowDateOverride(true)}
                  disabled={isPending}
                  className="w-full gap-2"
                  size="lg"
                >
                  <CalendarDays className="h-4 w-4" />
                  Override Event Date
                  <kbd className="ml-auto rounded border border-border bg-muted px-1.5 py-0.5 text-xs">
                    E
                  </kbd>
                </Button>
              ) : (
                <div className="space-y-2 rounded-md border border-border bg-muted/30 p-3">
                  <Label htmlFor="eval-date-override" className="text-sm text-foreground/70">
                    Corrected event date
                  </Label>
                  <Input
                    id="eval-date-override"
                    type="date"
                    className="text-sm"
                    value={dateValue}
                    onChange={(e) => setDateValue(e.target.value)}
                    autoFocus
                    onKeyDown={(e) => {
                      if (e.key === "Escape") {
                        setShowDateOverride(false);
                        setDateValue("");
                      }
                    }}
                  />
                  <p className="text-xs text-muted-foreground">
                    Set the correct date, then press Correct or Wrong above.
                  </p>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="w-full"
                    onClick={() => {
                      setShowDateOverride(false);
                      setDateValue("");
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          </div>

          {/* RIGHT PANEL — Note viewer */}
          <div className="rounded-lg border border-border bg-card">
            <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
              <span className="text-sm font-medium text-foreground">
                Matched Notes
              </span>
              {noteContext && (
                <span className="text-xs text-muted-foreground">
                  {noteContext.notes.length} note
                  {noteContext.notes.length !== 1 ? "s" : ""}
                </span>
              )}
            </div>
            <div className="h-[560px] overflow-y-auto p-4">
              {notesLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-5/6" />
                  <Skeleton className="h-4 w-4/6" />
                </div>
              ) : noteContext ? (
                <EvalNoteViewer
                  notes={noteContext.notes}
                  keywords={noteContext.search_keywords}
                />
              ) : (
                <p className="text-sm text-muted-foreground">
                  Note context unavailable.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/projects/evaluation/EvalReviewPanel.tsx
git commit -m "feat: add EvalReviewPanel with two-column clinical review layout"
```

---

## Task 6: Frontend — Wire Review Panel into Evaluation Session Page

**Files:**
- Modify: `frontend/src/projects/evaluation/ResultsSection.tsx`
- Modify: `frontend/src/projects/evaluation/EvaluationSessionPage.tsx`

- [ ] **Step 1: Add review mode toggle to ResultsSection**

Replace the header `div` in `ResultsSection` (the one containing `<h2>Patient Results</h2>` and the tab buttons) with a version that includes a review mode toggle:

In `frontend/src/projects/evaluation/ResultsSection.tsx`, update the props interface and add the toggle:

```tsx
interface ResultsSectionProps {
  projectId: string;
  sessionId: string;
  sessionStatus: string;
  onRefresh: () => void;
  reviewMode: boolean;
  onToggleReviewMode: () => void;
}
```

Update the function signature:

```tsx
export default function ResultsSection({
  projectId,
  sessionId,
  sessionStatus,
  onRefresh,
  reviewMode,
  onToggleReviewMode,
}: ResultsSectionProps) {
```

Replace the header section (the `<div className="flex items-center justify-between">` containing the h2 and tabs) with:

```tsx
<div className="flex items-center justify-between">
  <h2 className="text-lg font-semibold">Patient Results</h2>
  <div className="flex items-center gap-3">
    {sessionStatus === "reviewing" && (
      <Button
        variant={reviewMode ? "default" : "outline"}
        size="sm"
        onClick={onToggleReviewMode}
      >
        {reviewMode ? "Show List" : "Start Review"}
      </Button>
    )}
    {!reviewMode && (
      <div className="flex gap-1 rounded-md bg-muted p-0.5">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => { setActiveTab(tab); setPage(1); }}
            className={`rounded-sm px-3 py-1 text-xs capitalize ${
              activeTab === tab ? "bg-primary text-primary-foreground" : "text-muted-foreground"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>
    )}
  </div>
</div>
```

Then wrap the existing results list in `{!reviewMode && (...)}`  so it hides when review mode is active. The review panel itself is rendered by the parent.

- [ ] **Step 2: Update EvaluationSessionPage to manage review mode**

In `frontend/src/projects/evaluation/EvaluationSessionPage.tsx`, add state and render the review panel:

Add imports:
```tsx
import { useState } from "react";
import EvalReviewPanel from "./EvalReviewPanel";
```

Update the existing `useState` / `useParams` section (existing code already has `useParams` and `useQueryClient`):

```tsx
const [reviewMode, setReviewMode] = useState(false);
```

Update the `ResultsSection` usage to pass the new props:

```tsx
<ResultsSection
  projectId={projectId!}
  sessionId={session.id}
  sessionStatus={session.status}
  onRefresh={refresh}
  reviewMode={reviewMode}
  onToggleReviewMode={() => setReviewMode((v) => !v)}
/>

{reviewMode && session.status === "reviewing" && (
  <EvalReviewPanel
    projectId={projectId!}
    sessionId={session.id}
    onRefresh={refresh}
  />
)}
```

- [ ] **Step 3: Verify the app compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/projects/evaluation/ResultsSection.tsx frontend/src/projects/evaluation/EvaluationSessionPage.tsx
git commit -m "feat: wire EvalReviewPanel into evaluation session page with toggle"
```

---

## Task 7: Integration Verification

- [ ] **Step 1: Run all backend tests**

Run: `cd backend && uv run pytest -v -x`
Expected: ALL PASS, including new `test_eval_review.py` tests.

- [ ] **Step 2: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Manual smoke test**

1. Start backend: `cd backend && uv run uvicorn app.main:create_app --factory --reload`
2. Start frontend: `cd frontend && npm run dev`
3. Navigate to an evaluation session in "reviewing" status
4. Click "Start Review" button in the Patient Results section
5. Verify: two-column layout appears with patient info (left) and notes (right)
6. Verify: LLM prediction shows label, confidence, reasoning
7. Verify: matched notes show full text with keyword highlighting
8. Verify: evidence notes are tagged with "LLM Evidence" badge
9. Verify: Correct/Wrong/Skip buttons work and advance to next patient
10. Verify: keyboard shortcuts (C/W/S/E/?) work
11. Verify: event date override pre-fills from LLM's proposed date
12. Verify: after all patients reviewed, completion message appears

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: unified clinical review UI for evaluation sessions

Replace card-list ResultsSection with annotation-style two-column review:
- Left panel: patient info, LLM prediction, judgment actions
- Right panel: full note context with keyword highlights
- Sequential patient navigation with progress tracking
- Keyboard shortcuts (C/W/S/E/?)
- Event date override with LLM pre-fill
- New backend endpoints: next-unreviewed, result-notes"
```
