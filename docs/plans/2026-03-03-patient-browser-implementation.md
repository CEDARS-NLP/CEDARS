# Patient Browser Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a searchable patient browser with note viewer and re-open capability for attending oversight of annotation decisions.

**Architecture:** Extend existing `connectors` service with search/filter/count on `list_patients`. Add a `reopen_patient` endpoint to annotations. Build two new React pages (patient list + patient detail) and wire into sidebar navigation.

**Tech Stack:** FastAPI, SQLAlchemy, React + TypeScript, TanStack Query, shadcn/ui, Lucide icons

---

### Task 1: Backend — Add search, filter, and count to `list_patients`

**Files:**
- Modify: `backend/app/connectors/service.py:285-311` (`list_patients` function)
- Modify: `backend/app/connectors/router.py:205-223` (`list_patients_endpoint`)
- Modify: `backend/app/connectors/schemas.py:46-51` (`PatientResponse`)
- Test: `backend/tests/test_connectors_api.py`

**Step 1: Write the failing test**

Add to `backend/tests/test_connectors_api.py`:

```python
class TestPatientSearch:
    async def _ingest_patients(self, client):
        """Helper: register, create project, ingest 3 patients."""
        await register_and_login(client)
        project_id = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{project_id}/data/sources",
            json={
                "name": "test.csv",
                "connector_type": "file_upload",
                "config": {
                    "s3_key": "test.csv",
                    "file_type": "csv",
                    "column_mapping": {
                        "patient_id": "patient_id",
                        "text_id": "text_id",
                        "text": "text",
                        "note_date": "date",
                    },
                },
            },
        )
        ds_id = create_resp.json()["id"]

        csv_data = (
            b"patient_id,text_id,text,date\n"
            b"MRN001,N001,Note one,2024-01-01\n"
            b"MRN002,N002,Note two,2024-01-02\n"
            b"MRN003,N003,Note three,2024-01-03\n"
        )
        with patch("app.connectors.file_upload.download_file", return_value=csv_data):
            await client.post(
                f"/api/v1/projects/{project_id}/data/sources/{ds_id}/ingest",
            )
        return project_id

    async def test_search_patients_by_ext_id(self, client):
        project_id = await self._ingest_patients(client)

        resp = await client.get(
            f"/api/v1/projects/{project_id}/data/patients?search=MRN001"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(p["patient_id_ext"] == "MRN001" for p in data["items"])

    async def test_search_patients_case_insensitive(self, client):
        project_id = await self._ingest_patients(client)

        resp = await client.get(
            f"/api/v1/projects/{project_id}/data/patients?search=mrn00"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3

    async def test_filter_patients_by_status(self, client):
        project_id = await self._ingest_patients(client)

        resp = await client.get(
            f"/api/v1/projects/{project_id}/data/patients?status=new"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert all(p["status"] == "new" for p in data["items"])

    async def test_patients_response_includes_total(self, client):
        project_id = await self._ingest_patients(client)

        resp = await client.get(
            f"/api/v1/projects/{project_id}/data/patients?limit=1"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 1
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_connectors_api.py::TestPatientSearch -v`
Expected: FAIL — `search` param not handled, response is a list not a dict with `total`/`items`

**Step 3: Update the schema**

In `backend/app/connectors/schemas.py`, add:

```python
class PatientListResponse(BaseModel):
    items: list[PatientResponse]
    total: int
    limit: int
    offset: int
```

**Step 4: Update the service**

In `backend/app/connectors/service.py`, modify `list_patients` to accept `search` and `status` params:

```python
async def list_patients(
    session: AsyncSession,
    project_id: str,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    status: str | None = None,
) -> dict:
    """List patients with note counts, optional search and filter."""
    base_where = [Patient.project_id == project_id, Patient.deleted_at.is_(None)]

    if search:
        base_where.append(Patient.patient_id_ext.ilike(f"%{search}%"))
    if status:
        base_where.append(Patient.status == status)

    # Count total matching
    count_stmt = select(func.count()).select_from(Patient).where(*base_where)
    total = (await session.execute(count_stmt)).scalar() or 0

    # Fetch page with note counts
    stmt = (
        select(
            Patient,
            func.count(Note.id).label("note_count"),
        )
        .outerjoin(Note, (Note.patient_id == Patient.id) & Note.deleted_at.is_(None))
        .where(*base_where)
        .group_by(Patient.id)
        .order_by(Patient.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    items = [
        {"patient": row[0], "note_count": row[1]}
        for row in result.all()
    ]

    return {"items": items, "total": total, "limit": limit, "offset": offset}
```

**Step 5: Update the router**

In `backend/app/connectors/router.py`, update `list_patients_endpoint`:

```python
@router.get("/patients", response_model=PatientListResponse)
async def list_patients_endpoint(
    project_id: str,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    result = await list_patients(
        session, project_id, limit=limit, offset=offset, search=search, status=status,
    )
    return PatientListResponse(
        items=[
            PatientResponse(
                id=r["patient"].id,
                patient_id_ext=r["patient"].patient_id_ext,
                status=r["patient"].status.value,
                note_count=r["note_count"],
                created_at=r["patient"].created_at,
            )
            for r in result["items"]
        ],
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )
```

**Step 6: Run tests to verify they pass**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_connectors_api.py::TestPatientSearch -v`
Expected: PASS

**Step 7: Fix any existing tests that relied on old list format**

The `TestIngestion.test_ingest_csv_data` test uses the old list response format. Update it:

```python
# Old:
patients = patients_resp.json()
# New:
patients = patients_resp.json()["items"]
```

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_connectors_api.py -v`
Expected: ALL PASS

**Step 8: Commit**

```bash
git add backend/app/connectors/service.py backend/app/connectors/router.py backend/app/connectors/schemas.py backend/tests/test_connectors_api.py
git commit -m "feat: add search, filter, and pagination to patient list endpoint"
```

---

### Task 2: Backend — Add `reopen_patient` endpoint

**Files:**
- Modify: `backend/app/annotations/service.py` (add `reopen_patient` function)
- Modify: `backend/app/annotations/router.py` (add route)
- Test: `backend/tests/test_annotations_api.py`

**Step 1: Write the failing test**

Add to `backend/tests/test_annotations_api.py`:

```python
class TestReopenPatient:
    async def test_reopen_reviewed_patient(self, client):
        """POST /patient/{id}/reopen sets patient back to NLP_COMPLETE and clears lock."""
        pid = await _full_setup(client, use_dates=True)

        # Get and review all annotations for first patient
        next_resp = await client.get(f"/api/v1/projects/{pid}/annotations/patient/next")
        patient_id = next_resp.json()["patient_id"]

        annos = (await client.get(
            f"/api/v1/projects/{pid}/annotations/patient/{patient_id}/annotations"
        )).json()

        for ann in annos:
            if ann["review_status"] == "unreviewed":
                await client.post(
                    f"/api/v1/projects/{pid}/annotations/{ann['id']}/review",
                    json={},
                )

        # Verify patient is reviewed
        stats = (await client.get(
            f"/api/v1/projects/{pid}/annotations/patient/{patient_id}/stats"
        )).json()
        assert stats["unreviewed"] == 0

        # Reopen
        resp = await client.post(
            f"/api/v1/projects/{pid}/annotations/patient/{patient_id}/reopen",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "nlp_complete"
        assert data["locked_by"] is None

    async def test_reopen_preserves_annotation_decisions(self, client):
        """POST /patient/{id}/reopen does NOT reset annotation review_status."""
        pid = await _full_setup(client, use_dates=True)

        next_resp = await client.get(f"/api/v1/projects/{pid}/annotations/patient/next")
        patient_id = next_resp.json()["patient_id"]

        annos = (await client.get(
            f"/api/v1/projects/{pid}/annotations/patient/{patient_id}/annotations"
        )).json()

        for ann in annos:
            if ann["review_status"] == "unreviewed":
                await client.post(
                    f"/api/v1/projects/{pid}/annotations/{ann['id']}/review",
                    json={},
                )

        # Reopen
        await client.post(
            f"/api/v1/projects/{pid}/annotations/patient/{patient_id}/reopen",
        )

        # Annotations should still be reviewed
        annos_after = (await client.get(
            f"/api/v1/projects/{pid}/annotations/patient/{patient_id}/annotations"
        )).json()
        assert all(a["review_status"] in ("reviewed", "skipped") for a in annos_after)

    async def test_reopen_nonexistent_patient(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.post(
            f"/api/v1/projects/{pid}/annotations/patient/nonexistent/reopen",
        )
        assert resp.status_code == 404
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_annotations_api.py::TestReopenPatient -v`
Expected: FAIL — 404 (route doesn't exist)

**Step 3: Write the service function**

Add to `backend/app/annotations/service.py`:

```python
async def reopen_patient(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
) -> Patient | None:
    """Re-queue a patient for review without resetting annotation decisions.

    Sets patient status to NLP_COMPLETE and clears the review lock.
    Annotations keep their reviewed/skipped status — the reviewer can
    selectively change individual annotations when they re-enter the queue.
    """
    patient = (
        await session.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.project_id == project_id,
            )
        )
    ).scalar_one_or_none()

    if not patient:
        return None

    patient.status = PatientStatus.NLP_COMPLETE
    patient.locked_by = None
    patient.locked_at = None
    session.add(patient)
    await session.commit()
    await session.refresh(patient)
    return patient
```

**Step 4: Write the route**

Add to `backend/app/annotations/router.py` (in the patient-first review section, before `/{annotation_id}`):

```python
@router.post("/patient/{patient_id}/reopen")
async def reopen_patient_endpoint(
    project_id: str,
    patient_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Re-queue a reviewed patient. Admin only. Preserves annotation decisions."""
    patient = await reopen_patient(session, project_id, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return {
        "id": patient.id,
        "patient_id_ext": patient.patient_id_ext,
        "status": patient.status.value,
        "locked_by": patient.locked_by,
    }
```

Update the imports at the top of `router.py` to include `reopen_patient`.

**Step 5: Run tests to verify they pass**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_annotations_api.py::TestReopenPatient -v`
Expected: PASS

**Step 6: Run full test suite**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest -v`
Expected: ALL PASS

**Step 7: Commit**

```bash
git add backend/app/annotations/service.py backend/app/annotations/router.py backend/tests/test_annotations_api.py
git commit -m "feat: add reopen patient endpoint for attending oversight"
```

---

### Task 3: Frontend — Add Patients page to sidebar and routing

**Files:**
- Modify: `frontend/src/components/AppSidebar.tsx:17-24` (add nav item)
- Modify: `frontend/src/App.tsx` (add routes)
- Create: `frontend/src/projects/PatientsPage.tsx`
- Create: `frontend/src/projects/PatientDetailPage.tsx`

**Step 1: Add sidebar nav item**

In `frontend/src/components/AppSidebar.tsx`, add to the imports:

```typescript
import { Users } from "lucide-react";
```

Add to `projectNavSections` array (after Data, before Pipeline):

```typescript
{ label: "Patients", suffix: "/patients", icon: Users },
```

**Step 2: Create stub PatientsPage**

Create `frontend/src/projects/PatientsPage.tsx`:

```tsx
export default function PatientsPage() {
  return <div>Patients page placeholder</div>;
}
```

**Step 3: Create stub PatientDetailPage**

Create `frontend/src/projects/PatientDetailPage.tsx`:

```tsx
export default function PatientDetailPage() {
  return <div>Patient detail placeholder</div>;
}
```

**Step 4: Add routes to App.tsx**

Add imports:

```typescript
import PatientsPage from "@/projects/PatientsPage";
import PatientDetailPage from "@/projects/PatientDetailPage";
```

Add routes inside the `<Route path="/projects/:projectId" element={<ProjectLayout />}>` block, after the `data` route:

```tsx
<Route path="patients" element={<PatientsPage />} />
<Route path="patients/:patientId" element={<PatientDetailPage />} />
```

**Step 5: Verify app compiles**

Run: `cd /Users/rsingh/Programming/CEDARS/frontend && npx tsc --noEmit`
Expected: No errors

**Step 6: Commit**

```bash
git add frontend/src/components/AppSidebar.tsx frontend/src/App.tsx frontend/src/projects/PatientsPage.tsx frontend/src/projects/PatientDetailPage.tsx
git commit -m "feat: add patients page stubs and sidebar navigation"
```

---

### Task 4: Frontend — Build PatientsPage (searchable list)

**Files:**
- Modify: `frontend/src/projects/PatientsPage.tsx` (full implementation)

**Step 1: Implement the full PatientsPage**

Replace the stub in `frontend/src/projects/PatientsPage.tsx` with the full implementation. The page needs:

1. **Search bar** — debounced input (300ms) that sets `search` query param
2. **Status filter** — dropdown select with options: All, New, NLP Processing, NLP Complete, Reviewing, Reviewed
3. **Patient table** — columns: Patient ID, Status (badge), Notes, Created
4. **Pagination** — Previous/Next buttons with page info, based on `total`/`limit`/`offset` from API
5. **Row click** — navigates to `/projects/:projectId/patients/:patientId`

API call: `GET /api/v1/projects/{projectId}/data/patients?search=X&status=Y&limit=20&offset=Z`

Key implementation details:

```tsx
import { useState, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Search, ChevronLeft, ChevronRight, Users } from "lucide-react";
import { api } from "@/api/client";
import WorkflowBreadcrumb from "@/components/WorkflowBreadcrumb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
```

Use `useQuery` with `queryKey: ["patients", projectId, search, status, offset]` to fetch from `GET /data/patients`.

Use a `useEffect` + `setTimeout` for 300ms debounce on the search input, storing `searchInput` (immediate) and `search` (debounced) separately.

Status badge colors:
- `new` → secondary (gray)
- `nlp_processing` → accent/blue
- `nlp_complete` → amber
- `reviewing` → purple
- `reviewed` → emerald

**Step 2: Verify it compiles**

Run: `cd /Users/rsingh/Programming/CEDARS/frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/projects/PatientsPage.tsx
git commit -m "feat: implement searchable patient list page"
```

---

### Task 5: Frontend — Build PatientDetailPage

**Files:**
- Modify: `frontend/src/projects/PatientDetailPage.tsx` (full implementation)

**Step 1: Implement the PatientDetailPage**

Replace the stub with the full implementation. The page needs:

1. **Back link** — `< Back to patients` link to `/projects/:projectId/patients`
2. **Patient header** — MRN, status badge
3. **Annotation stats** — fetched from `GET /annotations/patient/{patientId}/stats`
4. **Re-open button** — shown only for admin users (check via `useAuth()` or project role), with confirmation dialog. Calls `POST /annotations/patient/{patientId}/reopen`. After success, refetch patient data.
5. **Notes list** — fetched from `GET /data/patients/{patientId}/notes`. Each note is a collapsible card showing:
   - Header: text_id + note_date
   - Body (collapsed by default): full note text with annotated sentences highlighted
6. **Annotations overlay** — fetched from `GET /annotations/patient/{patientId}/annotations`. Group by `note_id`. For each note, show annotation badges inline:
   - Sentence text with highlight
   - Review status badge (reviewed/skipped/unreviewed)
   - Prediction label + score
   - Event date if set

API calls:
- `GET /data/patients/{patientId}/notes` — note list
- `GET /annotations/patient/{patientId}/annotations` — annotations grouped by note
- `GET /annotations/patient/{patientId}/stats` — summary stats
- `POST /annotations/patient/{patientId}/reopen` — re-open action

Key imports:

```tsx
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, ChevronDown, ChevronRight, CheckCircle2,
  RotateCcw, CalendarDays, AlertTriangle,
} from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
```

Reuse the `highlightMatches` utility pattern from `AnnotationsPage.tsx` for consistency.

For the re-open button, use a simple `window.confirm()` dialog — no need for a shadcn dialog component for this.

**Step 2: Verify it compiles**

Run: `cd /Users/rsingh/Programming/CEDARS/frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/projects/PatientDetailPage.tsx
git commit -m "feat: implement patient detail page with notes and annotation viewer"
```

---

### Task 6: Integration verification

**Step 1: Run full backend test suite**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest -v`
Expected: ALL PASS

**Step 2: Run frontend type check**

Run: `cd /Users/rsingh/Programming/CEDARS/frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Run frontend lint**

Run: `cd /Users/rsingh/Programming/CEDARS/frontend && npx eslint src/projects/PatientsPage.tsx src/projects/PatientDetailPage.tsx`
Expected: No errors (or only minor warnings)

**Step 4: Commit any fixes**

If lint/type issues found, fix and commit:

```bash
git commit -m "fix: address lint and type issues in patient browser"
```
