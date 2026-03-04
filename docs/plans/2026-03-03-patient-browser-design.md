# Patient Browser Design

## Problem

Once a patient is fully reviewed in the annotation queue, their notes and annotation decisions become inaccessible. In clinical workflows, an attending needs to look up specific patients to verify a fellow's annotation decisions. There is no search, no patient list, and no way to view reviewed notes.

## Solution

A dedicated **Patients** page accessible from the sidebar, providing:

1. Searchable, filterable patient list
2. Patient detail view with chronological notes and annotation decisions (read-only)
3. Admin "re-open for review" action that re-queues a patient without wiping existing decisions

## Approach

Dedicated sidebar page (not a tab on Annotations or Data). The annotation queue remains the primary review workflow; the patient browser is a parallel read-only access path for oversight and lookup.

## Backend Changes

### Existing endpoints (no changes)

- `GET /projects/{project_id}/data/patients` — list patients with note count
- `GET /projects/{project_id}/data/patients/{patient_id}/notes` — full notes
- `GET /projects/{project_id}/annotations/patient/{patient_id}/annotations` — all annotations
- `GET /projects/{project_id}/annotations/patient/{patient_id}/stats` — review stats

### Modifications

**`GET /data/patients`** — add query parameters:
- `search` (str, optional): filter by `patient_id_ext` using case-insensitive contains
- `status` (str, optional): filter by `PatientStatus` value

Add `total` count to response for pagination (return as a header or wrapper).

### New endpoint

**`POST /annotations/patient/{patient_id}/reopen`** (admin only):
- Sets patient status back to `NLP_COMPLETE`
- Clears `locked_by` / `locked_at`
- Does NOT reset annotation decisions — reviewed/skipped status is preserved
- Patient re-appears in the annotation queue; reviewer can selectively change individual annotations

## Frontend

### Sidebar

Add "Patients" nav item with `Users` icon, positioned between Data and Pipeline.

### Patient List Page

**Route**: `/projects/:projectId/patients`

- Search bar (debounced, searches by MRN/patient_id_ext)
- Status filter dropdown (All, New, NLP Processing, NLP Complete, Reviewing, Reviewed)
- Patient table:
  - Patient ID (ext)
  - Status badge
  - Note count
  - Annotation summary (reviewed/total, event date indicator)
  - Created date
- Pagination
- Rows clickable → patient detail

### Patient Detail Page

**Route**: `/projects/:projectId/patients/:patientId`

- Back link to patient list
- Patient header: MRN, status badge, annotation stats
- Re-open button (admin only, with confirmation)
- Chronological notes list:
  - Each note: text_id, date, text (collapsed by default, expandable)
  - Annotated sentences highlighted within note text
  - Annotation details shown inline: review status, prediction, event date
  - Read-only — no inline editing

## Access Control

- All project members (admin, annotator, viewer) can browse patients and view notes/annotations
- Only admins can use the "re-open for review" action
