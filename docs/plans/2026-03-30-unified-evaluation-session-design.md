# Unified Evaluation Session Design

**Date:** 2026-03-30
**Status:** Approved
**Supersedes:** Separate EventConfig + Evaluation pages (agentic pipeline redesign)

## Problem

The current v2 design has two separate flows: an EventConfig/Pipeline page for configuring search patterns + LLM, and a separate Evaluation page for validating LLM performance. This split creates unnecessary friction — clinicians must jump between pages, and the relationship between search filters and LLM evaluation isn't obvious. Starting over requires navigating multiple pages.

## Solution

Merge everything into a single **Evaluation Session** concept. Each session is a self-contained workspace where the clinician:

1. Configures search queries (with LLM assistance)
2. Previews matched notes with highlighted keywords
3. Configures the LLM prompt
4. Runs LLM classification on matched patients
5. Reviews results and judges correctness
6. Commits — locking the config and running on the full corpus

Sessions are cheap and disposable. If something isn't working, discard and start a new one.

## Session Lifecycle

### States

| State | Description | Editable | Can Discard |
|-------|-------------|----------|-------------|
| **DRAFT** | Working on queries and/or LLM config. Not yet reviewed. | Yes | Yes (instant) |
| **REVIEWING** | LLM has run on sample. Clinician judging results. | Yes (can re-run) | Yes (instant) |
| **COMMITTED** | Locked. Full pipeline running on corpus. | No | No (cancel run first) |
| **COMPLETED** | Full pipeline finished. | No | No |
| **DISCARDED** | Thrown away. Kept for history. | No | N/A |

### Rules

- Only **one active session** (DRAFT or REVIEWING) at a time per project
- **"+ New Session"** discards any current draft automatically
- **Discard is instant** — no confirmation dialog
- **Commit** locks the session and triggers the full corpus run
- **No new sessions while a COMMITTED run is active** — must cancel the run first
- New sessions can optionally **clone queries + prompt from a previous session**

## Page Layout

Single scrollable page with collapsible sections. A **pinned funnel bar** stays at the top showing filtering impact at all times.

### Pinned Funnel Bar

Always visible at the top of the session page:

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Sample     │ ──► │ Search Match │ ──► │ LLM Positive │
│ 1,240 pts    │     │ 187 pts      │     │ 43 pts       │
│ 12,400 notes │     │ 97% filtered │     │ 23% of match │
└──────────────┘     └──────────────┘     └──────────────┘

97% of notes filtered by search — est. LLM cost: ~$0.85
```

- Updates live as queries change (search match) and after LLM runs (LLM positive)
- Shows filter percentage and estimated LLM cost
- LLM section grayed out until LLM has been run

### Section 1: Search Queries

Clinician-friendly query syntax (parsed to spaCy Matcher patterns under the hood):

| Syntax | Meaning |
|--------|---------|
| `troponin OR MI` | Match notes containing either term |
| `(ECG OR EKG) AND elevation` | Both conditions must match in same note |
| `embol*` | Wildcard: matches embolism, emboli, embolus, etc. |
| `!suspected` | Exclude notes containing this term |
| `(DVT OR PE) AND !suspected` | Combined include + exclude |

**Features:**

- **Query list** with per-query stats: notes matched, patients matched, top matching term
- **Add/edit/delete** queries with include/exclude toggle
- **"Suggest Queries" LLM button**: clinician describes the event in plain English, LLM returns suggested queries. Clinician can accept/edit/skip each suggestion individually.
- **Syntax help** displayed inline
- Multiple include queries are OR'd together (note matching any query is included)
- Exclude queries subtract from the result set
- Built-in **negation detection** via spaCy (e.g., "no troponin elevation" auto-excluded)

**Note preview (expand per query):**

- Click any query row to expand and see all matched notes
- Keywords highlighted inline (blue highlights for matches, red strikethrough for spaCy-negated matches)
- Filter by patient ID, sort by match count / date / patient
- Paginated (10 notes per page)
- No LLM-powered insights at this stage — just keyword highlighting and spaCy negation

### Section 2: LLM Classification

**Configuration:**

- **Event name**: e.g., "Myocardial Infarction"
- **Event description**: natural language description of the event
- **Include criteria**: what to look for (free text, shown to LLM)
- **Exclude criteria**: what to exclude (free text, shown to LLM)
- **LLM provider**: OpenAI, Anthropic, Ollama, AWS Bedrock
- **LLM model**: model selection per provider

**Execution:**

- **1 LLM call per matched patient** — sends all matched note excerpts for that patient, sorted chronologically with dates
- LLM returns: **label** (positive/negative/inconclusive), **event date** (earliest confirmed, if positive), **confidence score**, **reasoning**, **evidence excerpts**
- The prompt explicitly instructs the LLM to identify the **earliest confirmed occurrence** of the event
- Progress bar with cancel support (completed patients keep results)
- Can re-run after changing prompt — clears LLM results, preserves search matches

**Cost display:**

- Before run: estimated cost based on matched patient count and avg note size
- After run: actual token usage and cost

### Section 3: Review

**Patient cards:**

- Expanded view for positives: classification, confidence score, event date, reasoning, evidence excerpts with note dates
- Collapsed view for negatives: one-line summary with inline judgment buttons
- Already-reviewed patients show their judgment inline

**Filter tabs:** All | Positive | Negative | Inconclusive | Unreviewed

**Judgment per patient:**

- **Correct / Wrong / Skip** buttons
- **Event date override** field (pre-filled with LLM's answer)
- Navigation: Previous / Next Unreviewed

**Live metrics** (update as reviews come in):

- Accuracy, Precision, Recall, F1
- Based on reviewed patients count
- No requirement to review all patients before committing

### Section 4: Commit

- Shows full corpus size and cost estimate (extrapolated from sample match rate)
- **"Commit & Run Full Pipeline"** button locks queries + prompt and triggers full run
- Links to jump back to edit queries or prompt if not ready
- After commit: session becomes read-only, pipeline runs on all patients

## Sampling

- **Minimum 100 patients** sampled when session starts
- If cohort has fewer than 100 patients, sample the entire cohort
- Sample is fixed for the session lifetime — query changes re-run against the same sample
- Sample drawn randomly from all patients in the project

## Data Model Changes

### EvaluationSession (replaces both EventConfig and EvaluationSession)

```
EvaluationSession:
  id: UUID (PK)
  project_id: UUID (FK)

  # Status
  status: draft | reviewing | committed | completed | discarded

  # Search queries (stored as structured list)
  search_queries: JSON          # [{ query: str, type: "include" | "exclude" }]

  # LLM configuration
  event_name: str | null
  event_description: str | null
  include_criteria: str | null
  exclude_criteria: str | null
  llm_provider: str | null
  llm_model: str | null
  llm_api_base: str | null

  # Sample
  sample_patient_ids: JSON      # List of patient UUIDs in the sample
  sample_size: int

  # Metrics (updated as reviews come in)
  metrics: JSON | null          # { accuracy, precision, recall, f1, reviewed, correct, wrong, skipped }

  # Config snapshot (frozen at commit time)
  committed_config: JSON | null # Full frozen config for the pipeline run
  committed_at: datetime | null
  committed_by: UUID (FK) | null

  # Cloned from
  cloned_from_id: UUID (FK) | null

  created_by: UUID (FK)
  created_at, updated_at: datetime
```

### SearchMatch (new — per-query match results on sample)

```
SearchMatch:
  id: bigint (PK)
  session_id: UUID (FK)
  query_index: int              # Which query in the list
  patient_id: UUID (FK)
  note_id: UUID (FK)
  matched_tokens: JSON          # List of matched token strings
  match_positions: JSON         # [{ start: int, end: int, token: str }]
  is_negated: bool              # spaCy negation detection
  created_at: datetime

  INDEX: (session_id, query_index)
  INDEX: (session_id, patient_id)
```

### PatientResult (replaces PatientTask for sample, reused for full run)

```
PatientResult:
  id: bigint (PK)
  session_id: UUID (FK)
  pipeline_run_id: UUID (FK) | null   # null for sample, set for full run
  patient_id: UUID (FK)

  # Search results
  notes_searched: int
  notes_matched: int

  # LLM classification
  finding_label: str | null           # positive | negative | inconclusive | no_match
  finding_reasoning: str | null
  finding_evidence: JSON | null       # [{ note_id, text, note_date }]
  event_date: date | null             # LLM's answer for earliest event date
  predicted_score: float | null
  token_usage: JSON | null

  # Clinician review
  review_judgment: str | null         # correct | wrong | skipped
  reviewer_date_override: date | null # Clinician's corrected event date
  reviewed_by: UUID (FK) | null
  reviewed_at: datetime | null

  # Execution
  status: queued | processing | completed | failed | no_match
  error_message: str | null
  started_at, completed_at: datetime

  INDEX: (session_id, status)
  INDEX: (pipeline_run_id, status)    # For SKIP LOCKED during full run
```

### PipelineRun (kept for full corpus runs)

```
PipelineRun:
  id: UUID (PK)
  session_id: UUID (FK)         # Links back to the committed session
  project_id: UUID (FK)
  status: queued | running | completed | failed | cancelled
  total_patients: int
  processed_patients: int
  failed_patients: int
  no_match_patients: int
  is_cancelled: bool
  result_summary: JSON | null
  started_at, completed_at, created_at: datetime
```

### Models Removed/Replaced

- `EventConfig` → merged into `EvaluationSession.search_queries` + LLM fields
- Separate `EvaluationSession` + `EvaluationJudgment` → unified into `EvaluationSession` + `PatientResult`
- `PatientTask` → replaced by `PatientResult` (serves both sample and full run)
- `Evidence` model → replaced by `SearchMatch` (for query preview) + `PatientResult.finding_evidence` (for LLM output)
- `ValidatedPredictor` → no longer needed; a committed session IS the validated config

### Models Unchanged

- `Patient`, `Note` — unchanged
- `Annotation` — still created from `PatientResult` after full pipeline run
- `BackgroundJob` — still used for INGESTION and EXPORT

## Full Pipeline Execution (After Commit)

When a session is committed:

1. Create a `PipelineRun` linked to the session
2. Create `PatientResult` rows for ALL patients in the project (status: `queued`)
3. Skip patients already processed in the sample (copy results, mark `completed`)
4. Workers pull patients via `SELECT ... FOR UPDATE SKIP LOCKED`
5. Per patient: run search queries → if matched, call LLM → store result
6. Create `Annotation` records from positive results
7. Results available to annotators immediately per-patient

### Cancellation

- Set `PipelineRun.is_cancelled = true`
- Workers check before each patient
- Unprocessed patients remain `queued`
- After cancellation, new evaluation sessions can be created

### Retry

- Retry failed: `UPDATE patient_result SET status = 'queued' WHERE status = 'failed'`
- Retry stalled: reset `processing` tasks older than timeout

## API Endpoints

```
# Sessions
POST   /projects/{id}/evaluation/sessions              # Create new session
GET    /projects/{id}/evaluation/sessions              # List sessions
GET    /projects/{id}/evaluation/sessions/{sid}        # Get session detail
DELETE /projects/{id}/evaluation/sessions/{sid}        # Discard session
POST   /projects/{id}/evaluation/sessions/{sid}/clone  # Clone from previous

# Search queries
PUT    /projects/{id}/evaluation/sessions/{sid}/queries         # Update query list
POST   /projects/{id}/evaluation/sessions/{sid}/queries/suggest # LLM suggest
GET    /projects/{id}/evaluation/sessions/{sid}/queries/{idx}/matches  # Note preview with highlights

# LLM
POST   /projects/{id}/evaluation/sessions/{sid}/run-llm        # Run LLM on matched sample patients
POST   /projects/{id}/evaluation/sessions/{sid}/cancel-llm     # Cancel LLM run

# Results & review
GET    /projects/{id}/evaluation/sessions/{sid}/results         # Patient results (filterable)
POST   /projects/{id}/evaluation/sessions/{sid}/results/{rid}/judge  # Submit judgment
GET    /projects/{id}/evaluation/sessions/{sid}/metrics         # Live metrics

# Commit & pipeline
POST   /projects/{id}/evaluation/sessions/{sid}/commit         # Commit and run full pipeline
GET    /projects/{id}/evaluation/sessions/{sid}/pipeline/stats  # Full run progress
POST   /projects/{id}/evaluation/sessions/{sid}/pipeline/cancel # Cancel full run
POST   /projects/{id}/evaluation/sessions/{sid}/pipeline/retry-failed  # Retry failed patients

# Funnel stats
GET    /projects/{id}/evaluation/sessions/{sid}/funnel          # Funnel bar data
```

## Frontend Structure

Single page component: `EvaluationSessionPage.tsx`

```
EvaluationSessionPage
├── FunnelBar (pinned)                    # Always visible at top
├── SearchQueriesSection                   # Query editor + suggest + stats
│   ├── QueryRow (per query)              # Expandable with note preview
│   │   └── NotePreviewList               # Paginated matched notes with highlights
│   └── AddQueryForm
├── LlmConfigSection                      # Event definition + model selection + run button
│   └── LlmProgressBar                   # Shown during run
├── ResultsSection                         # Patient cards + filter tabs
│   ├── PatientResultCard (per patient)   # Expanded/collapsed with judgment buttons
│   └── ReviewNavigation                  # Previous / Next Unreviewed
├── MetricsPanel                           # Live accuracy/precision/recall/F1
└── CommitSection                          # Cost estimate + commit button
```

Session list page: `EvaluationListPage.tsx`

```
EvaluationListPage
├── NewSessionButton
└── SessionCard (per session)             # Status badge, stats summary, open/discard
```

## What Gets Removed

- `EventConfigPage.tsx` — replaced by `EvaluationSessionPage.tsx`
- `EvaluationPage.tsx` (current multi-section page) — replaced
- `NlpQueriesSection.tsx` — absorbed into search queries section
- `PredictorConfigSection.tsx` — absorbed into LLM config section
- `SessionsSection.tsx` — absorbed into results/review section
- `ValidatedPredictorsSection.tsx` — no longer needed (committed session = validated config)
- `EventConfig` model — replaced by session fields
- `ValidatedPredictor` model — replaced by committed session
- Separate pipeline/evaluation router split — unified under evaluation router
