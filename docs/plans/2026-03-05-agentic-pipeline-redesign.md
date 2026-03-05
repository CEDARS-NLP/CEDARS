# Agentic Pipeline Redesign

**Date:** 2026-03-05
**Status:** Design approved, pending implementation plan

## Problem

Large cohort NLP processing (100K+ patients) takes too long as a blocking batch operation. The current architecture runs NLP and LLM predictions as separate sequential pipelines across the entire corpus before any results are available to annotators. This creates several issues:

- Long wait times before any results are reviewable
- No way to validate the pipeline configuration on a sample before committing to a full run
- Separate configuration and evaluation flows for NLP (regex) and LLM (predictions)
- Limited job management (no retry of failed patients, no job dashboard)

## Solution

Replace the separate NLP and LLM prediction pipelines with a **unified agentic pipeline** that processes patients one at a time, making results available immediately. The LLM acts as an agent with tools (keyword search, dynamic regex, note reading) to find clinical events in each patient's records.

### Core changes

| Aspect | Current | New |
|--------|---------|-----|
| Processing unit | Entire corpus (all notes, then all predictions) | Per-patient (NLP → LLM → annotation, one patient at a time) |
| NLP + LLM relationship | Two separate pipelines, separate configs | Unified agent — NLP tools serve the LLM's search |
| Configuration | SearchQuery + PredictorConfig separately | Single EventConfig (queries + LLM + event definition) |
| Evaluation | Separate eval for predictions only | Unified eval: run sample, review, calibrate, approve full run |
| Result availability | Only after full pipeline completes | Immediately per-patient as each completes |
| Job management | Per-pipeline cancel only | Full dashboard with cancel, retry failed, retry stalled |
| Annotation unit | Individual sentences | Patient-level finding with evidence excerpts |

## Architecture

### Per-Patient Agent

For each patient, an LLM agent runs a bounded tool-use loop:

```python
async def process_patient(patient_id, event_config, max_rounds=5):
    messages = [system_prompt(event_config)]

    for round in range(max_rounds):
        response = await llm.acompletion(messages, tools=TOOLS)

        if response.has_tool_calls:
            for tool_call in response.tool_calls:
                result = await execute_tool(tool_call, patient_id)
                messages.append(tool_result(result))

        if response.has_final_answer:
            return response.finding

    return Finding(label="inconclusive", reason="max rounds reached")
```

### Agent Tools

| Tool | Input | Output | Purpose |
|------|-------|--------|---------|
| `search_notes` | keyword query | Matching sentences with note context | Run clinician-defined keyword queries via spaCy matcher |
| `regex_search` | regex pattern | Matching note excerpts | Agent constructs dynamic regex to narrow search. Runs server-side with timeout protection. |
| `read_note` | note_id | Full note text | Read complete note when agent needs more context |
| `submit_finding` | label, evidence, reasoning | — | Record determination. Terminates the agent loop. |

The `search_notes` tool uses the existing spaCy NLP engine (tokenization, NegEx negation detection, keyword matching). The `regex_search` tool lets the agent construct targeted patterns dynamically — reducing the number of full notes sent to the LLM and saving tokens.

### System Prompt

```
You are a clinical event detection agent.

Event: {event_config.name}
Description: {event_config.description}
Include criteria: {event_config.include_criteria}
Exclude criteria: {event_config.exclude_criteria}

Search this patient's medical records for evidence of this event.
Use search_notes to find relevant mentions using keyword queries.
Use regex_search to construct targeted patterns for specific clinical values or phrases.
Use read_note if you need more context around a match.
Use submit_finding when you have enough evidence to make a determination.

If no evidence is found, submit a negative finding.
```

### Typical Agent Flow (example: Myocardial Infarction)

1. `search_notes("MI OR myocardial infarction OR heart attack")` → 3 matches across 50 notes
2. `regex_search("troponin.*(?:positive|elevated|>\\s*0\\.04)")` → 2 additional notes
3. `read_note(note_123)` → reads full cardiology consult note
4. `submit_finding(label="positive", evidence=[...], reasoning="Troponin elevated at 2.4, ECG shows ST elevation...")`

Result: Agent read 1-3 full notes instead of 50. Significant token savings.

## Data Model

### EventConfig (replaces SearchQuery + PredictorConfig)

```
EventConfig:
  id: UUID (PK)
  project_id: UUID (FK)
  name: str                           # e.g., "Myocardial Infarction"
  description: str                    # What the event is
  include_criteria: str               # Natural language include criteria
  exclude_criteria: str               # Natural language exclude criteria
  search_queries: JSON                # Array of keyword patterns
  llm_provider: str                   # e.g., "openai", "anthropic", "ollama"
  llm_model: str                      # e.g., "gpt-4o", "claude-sonnet-4-20250514"
  llm_api_base: str | null            # For self-hosted (vLLM, Ollama)
  max_agent_rounds: int (default 5)   # Bounded tool-use iterations
  confidence_threshold: float | null  # Calibrated from eval session
  is_committed: bool (default false)  # Locked after eval approval
  created_at, updated_at: datetime
```

### PipelineRun

```
PipelineRun:
  id: UUID (PK)
  project_id: UUID (FK)
  event_config_id: UUID (FK)
  run_type: "sample" | "full"
  status: queued | running | completed | failed | cancelled
  config_snapshot: JSON               # Frozen EventConfig at run time
  sample_size: int | null             # For sample runs
  total_patients: int
  is_cancelled: bool (default false)
  result_summary: JSON                # Aggregate stats after completion
  error_message: str | null
  created_by: UUID (FK)
  started_at, completed_at, created_at: datetime
```

### PatientTask

```
PatientTask:
  id: bigint (PK, auto-increment)
  pipeline_run_id: UUID (FK)
  patient_id: UUID (FK)
  status: queued | processing | completed | failed | skipped

  # Agent results
  agent_trace: JSON                   # Full tool-use audit trail
  notes_searched: int (default 0)
  notes_read: int (default 0)
  tool_calls: int (default 0)
  finding_label: str | null           # positive | negative | inconclusive
  finding_reasoning: str | null
  finding_evidence: JSON | null       # note_ids, sentence excerpts
  token_usage: JSON | null            # {prompt_tokens, completion_tokens}
  error_message: str | null

  started_at, completed_at: datetime
  INDEX: (pipeline_run_id, status)    # For worker queue pulls with SKIP LOCKED
```

### Evidence

```
Evidence:
  id: UUID (PK)
  patient_task_id: bigint (FK)
  note_id: UUID (FK)
  text: str                           # The extracted excerpt
  start_pos: int                      # Character offset in note.text
  end_pos: int                        # Character offset end
  match_source: str                   # "keyword_search" | "regex_search" | "full_note_read"
  match_query: str | null             # The query/regex that found this
  agent_round: int                    # Which tool-use round produced this
```

### Annotation (patient-level, replaces sentence-level)

```
Annotation:
  id: UUID (PK)
  project_id, patient_id: UUID (FK)
  pipeline_run_id: UUID (FK)
  patient_task_id: bigint (FK)

  # Agent determination
  predicted_label: str                # positive | negative | inconclusive
  predicted_reasoning: str
  predicted_score: float | null

  # Human review
  review_status: pending | confirmed | rejected
  reviewer_label: str | null
  event_date: date | null
  reviewer_notes: str | null
  reviewed_by: UUID (FK) | null
  reviewed_at: datetime | null
  created_at: datetime
```

### Models removed/replaced

- `SearchQuery` → merged into `EventConfig.search_queries`
- `PredictorConfig` → merged into `EventConfig`
- `NlpJob` → replaced by `PipelineRun`
- Separate NLP and PREDICTION BackgroundJob types → single PIPELINE type
- Sentence-level `Annotation` → patient-level `Annotation` with `Evidence` records

### Models unchanged

- `Patient`, `Note` — unchanged
- `Sentence` — still created by spaCy as tool output, but no longer the annotation unit
- `BackgroundJob` — still used for INGESTION and EXPORT job types

## Pipeline Flow

### Unified Workflow

```
1. CONFIGURE (Eval Page)
   ├── Define event (name, description, include/exclude criteria)
   ├── Set search queries (keyword patterns)
   ├── Configure LLM (provider, model)
   └── Iterate on sample until satisfied

2. RUN SAMPLE
   ├── PipelineRun(run_type="sample", sample_size=N)
   ├── Picks N random patients → creates PatientTasks
   ├── Per patient: agent loop (search → regex → read → submit_finding)
   ├── Creates Evidence records and Annotations
   └── Shows results in eval UI with metrics

3. REVIEW & CALIBRATE
   ├── User reviews sample predictions, marks correct/incorrect
   ├── System computes calibrated threshold from eval judgments
   ├── Shows precision/recall at different thresholds
   └── User "commits" the config (locks EventConfig)

4. RUN FULL PIPELINE
   ├── PipelineRun(run_type="full")
   ├── Creates PatientTask for ALL patients (sample patients already completed)
   ├── Workers pull patients via SELECT ... FOR UPDATE SKIP LOCKED
   ├── Multiple workers can process patients in parallel
   ├── Progress: real-time via WebSocket (patients completed / total)
   └── Results available in annotation UI immediately per-patient

5. ANNOTATE
   ├── Shows only predictions above calibrated threshold
   ├── Patient-first review: agent determination + evidence excerpts
   ├── Annotator sees highlighted evidence in full note context
   └── Confirm/reject with optional event date and notes
```

### Cost estimation

Progressive estimates using sample data:

1. **After sample NLP**: Extrapolate target sentence hit rate → "Estimated ~750 notes with target sentences out of 5,000"
2. **After sample LLM**: Extrapolate actual token usage per patient → "Estimated ~2.1M tokens for full cohort"

Since the LLM processes full notes (not just sentences), token counts vary significantly note-to-note. Sample-based estimation is far more accurate than raw character counting.

## Scaling

### Worker parallelism

Multiple ARQ workers process patients concurrently:

```sql
SELECT id, patient_id FROM patient_task
WHERE pipeline_run_id = :run_id AND status = 'queued'
ORDER BY id
LIMIT 1
FOR UPDATE SKIP LOCKED
```

Postgres advisory locks prevent conflicts. Each worker processes one patient at a time.

### Concurrent LLM calls per patient

For a patient with multiple notes containing target sentences, all LLM calls fire concurrently:

```python
results = await asyncio.gather(*[
    llm.acompletion(messages_for_note)
    for note in notes_with_targets
])
```

This is Level 1 batching. Level 2 (server-side batch APIs for vLLM, OpenAI Batch, Anthropic Batches) is deferred.

### Cancellation

- `PipelineRun.is_cancelled = True` → workers check before each patient
- Instant: no need to wait for current patient to finish (current patient completes, then stops)
- `PatientTask` status remains `queued` for unprocessed patients

### Retry

- **Retry failed**: `UPDATE patient_task SET status = 'queued' WHERE status = 'failed'`
- **Retry stalled**: Reset `processing` tasks older than timeout threshold back to `queued`
- Granular: can retry individual patients or all failures at once

### Resume after crash

Any `PatientTask` with `status = 'processing'` that stalled (no heartbeat) gets reset to `queued` on worker restart.

## Annotation Interface

### Patient-first review

```
Patient List (filtered by predicted_label + calibrated threshold)
  └── Patient Card
        ├── Agent Determination: "Positive — Myocardial Infarction"
        ├── Agent Reasoning: "Troponin elevated at 2.4, ECG shows ST elevation..."
        ├── Confidence: 0.87 (calibrated)
        ├── Evidence (3 excerpts across 2 notes):
        │     ├── Note 2024-01-15 (Cardiology Consult)
        │     │     └── "...troponin I elevated at [2.4 ng/mL], consistent with..."
        │     ├── Note 2024-01-15 (ED Admission)
        │     │     └── "...12-lead ECG showing [ST elevation in leads II, III, aVF]..."
        │     └── Note 2024-01-14 (ED Triage)
        │           └── "...patient presents with [crushing substernal chest pain]..."
        ├── [View Full Note] — expands note with evidence highlighted in-line
        └── Actions: [Confirm] [Reject] [Set Event Date] [Add Notes]
```

### Evidence highlighting

When annotator expands a note, evidence spans are highlighted using `start_pos`/`end_pos` from the Evidence model. Surrounding text provides clinical context.

### Filtering

- Predictions below the calibrated confidence threshold are hidden by default
- Annotator can adjust filter to see lower-confidence predictions if needed
- Filter by predicted label (positive/negative/inconclusive)

## Job Dashboard

New page at `/projects/:id/jobs` showing all pipeline runs and background jobs.

### Pipeline runs table

| Run | Type | Status | Progress | Patients | Started | Actions |
|-----|------|--------|----------|----------|---------|---------|
| #12 | Full | Running | 2,450 / 10,000 | 24.5% | 5 min ago | Cancel |
| #11 | Sample | Completed | 50 / 50 | 100% | 1 hr ago | View |
| #10 | Sample | Cancelled | 22 / 50 | — | 2 hrs ago | — |

### Expandable detail per run

- Patient task breakdown: completed / failed / skipped / queued
- Failed patients list with error messages + individual retry
- Token usage summary (prompt, completion, total)
- Config snapshot (queries, predictor, threshold)
- Agent trace viewer for individual patients

### Actions

- **Cancel**: Sets `is_cancelled=true`, workers stop after current patient
- **Retry failed**: Re-queues all `status=failed` patient tasks
- **Retry stalled**: Re-queues `processing` tasks older than timeout
- **View details**: Expand to see per-patient breakdown

### Other job types

Ingestion and export jobs shown in separate sections using existing `BackgroundJob` model.

## What Gets Removed

- Separate "Run NLP" and "Run Predictions" buttons/flows
- `NlpJob` model
- NLP and PREDICTION `BackgroundJob` types
- Sentence-level annotation workflow
- Separate `SearchQuery` and `PredictorConfig` configuration UIs

## Future Considerations (deferred)

- **Prompt caching**: Token usage JSON on PatientTask is extensible to track cache hits. Per-patient processing naturally groups shared system prompts.
- **Server-side batch APIs**: vLLM batch endpoint, OpenAI Batch API (50% cheaper), Anthropic Message Batches for cost optimization on large runs.
- **Sandboxed code execution**: `run_python` tool for agent to do complex data transformations. Requires RestrictedPython or container sandboxing for security.
- **Additional structured tools**: `search_by_date_range`, `extract_lab_values` for common clinical queries without code execution.
