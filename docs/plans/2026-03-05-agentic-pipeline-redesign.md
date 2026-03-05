# Agentic Pipeline Redesign (v2)

**Date:** 2026-03-05
**Status:** Design approved, pending implementation plan
**Supersedes:** Initial agentic design (per-patient agent loop) — replaced for scalability.

## Problem

Large cohort NLP processing (100K+ patients, 1M+ notes) takes too long as a blocking batch operation. The current architecture runs NLP and LLM predictions as separate sequential pipelines across the entire corpus before any results are available to annotators. This creates several issues:

- Long wait times before any results are reviewable
- No way to validate the pipeline configuration on a sample before committing to a full run
- Separate configuration and evaluation flows for NLP (regex) and LLM (predictions)
- Clinicians must write regex patterns manually instead of describing events in natural language
- Limited job management (no retry of failed patients, no job dashboard)

## Solution

Replace the separate NLP and LLM prediction pipelines with a **two-phase architecture** that separates interactive exploration from batch execution:

- **Phase 1 (Interactive):** An LLM agent helps the clinician build a search strategy from natural language. Runs on a sample for fast iteration and evaluation.
- **Phase 2 (Batch):** The approved search + classification pipeline runs per-patient across the full corpus. Results stream to annotators immediately as each patient completes.

### Core changes

| Aspect | Current | New |
|--------|---------|-----|
| Configuration | Clinician writes regex manually + configures LLM separately | Clinician describes event in natural language; LLM generates search patterns |
| Processing unit | Entire corpus (all notes NLP, then all predictions) | Per-patient (search → classify → annotate, one patient at a time) |
| Evaluation | Separate eval for LLM predictions only | Unified eval: sample run with both search + classification |
| Result availability | Only after full pipeline completes | Immediately per-patient as each completes |
| Scalability | O(corpus) LLM calls | O(matched notes) LLM calls — most notes never touch the LLM |
| Job management | Per-pipeline cancel only | Full dashboard with cancel, retry failed, retry stalled |
| Annotation unit | Individual sentences | Patient-level finding with evidence excerpts |

## Architecture

### Phase 1: Interactive Exploration (Sample)

The clinician works with an LLM agent to build a search strategy. This runs on a sample of patients (50-100) for fast iteration.

#### Step 1: Pattern Generation

Clinician provides a natural language event description. The LLM generates search patterns:

```
Clinician: "Find patients with confirmed myocardial infarction — troponin
            elevation, ECG changes, but not rule-outs or family history"

LLM generates:
{
  "keywords": ["troponin", "myocardial infarction", "MI", "STEMI", "NSTEMI"],
  "regex_patterns": [
    "troponin.*(?:elevated|positive|>\\s*0\\.04)",
    "(?:ST|EKG|ECG).*(?:elevation|changes)",
    "(?:confirmed|diagnosed).*(?:MI|myocardial)"
  ],
  "exclusion_patterns": ["rule.?out", "family history", "suspected"]
}
```

#### Step 2: Sample Search + Classification

Run the generated patterns on a sample of patients. For each patient with matches, the LLM classifies with one call per patient (sending matched note context):

```
Per sample patient:
  1. Run keywords + regex on all their notes     → deterministic, fast
  2. If matches found → 1 LLM classification call → label + reasoning + evidence
  3. Create annotation immediately
```

#### Step 3: Clinician Review + Calibration

Clinician reviews sample results:
- Sees generated patterns and match statistics
- Reviews each patient's classification (confirm/reject)
- System computes precision/recall/F1 from reviews
- Suggests calibrated confidence threshold
- Clinician can refine the natural language description and re-run

#### Step 4: Commit

Clinician approves the config. This locks the search patterns, LLM model, classification prompt, and calibrated threshold.

### Phase 2: Batch Execution (Full Corpus)

The approved pipeline runs per-patient across the full corpus:

```
Per patient (via PatientTask queue):
  1. Run committed search patterns on all their notes    → deterministic
  2. If no matches → mark as "no_match", skip LLM       → free
  3. If matches → 1 LLM classification call              → targeted
  4. Create annotation + evidence records                → immediately available
  5. Annotators can review this patient right away
```

Workers pull patients from the queue via `SELECT ... FOR UPDATE SKIP LOCKED`. Multiple workers process patients in parallel.

### Cost at Scale

| Cohort | Total Notes | Match Rate | LLM Calls | Batch API Cost (GPT-4o-mini) |
|--------|------------|------------|-----------|------------------------------|
| 1K patients | 5K | 10% | 500 | ~$0.25 |
| 10K patients | 50K | 10% | 5K | ~$2.50 |
| 100K patients | 500K | 10% | 50K (batchable) | ~$25 |

The LLM only touches notes with search matches. Most of the corpus is filtered deterministically.

## Data Model

### EventConfig (replaces SearchQuery + PredictorConfig)

```
EventConfig:
  id: UUID (PK)
  project_id: UUID (FK)

  # Event definition (natural language from clinician)
  name: str                            # e.g., "Myocardial Infarction"
  description: str                     # Natural language description
  include_criteria: str                # What to look for
  exclude_criteria: str                # What to exclude

  # LLM-generated search patterns (generated from description)
  search_patterns: JSON                # { keywords: [], regex_patterns: [], exclusion_patterns: [] }

  # LLM configuration
  llm_provider: str                    # e.g., "openai", "anthropic", "ollama"
  llm_model: str                       # e.g., "gpt-4o-mini", "claude-sonnet-4-20250514"
  llm_api_base: str | null             # For self-hosted (vLLM, Ollama)

  # Calibration (set after eval on sample)
  confidence_threshold: float | null   # Calibrated from eval session
  is_committed: bool (default false)   # Locked after eval approval

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
  config_snapshot: JSON                # Frozen EventConfig at run time
  sample_size: int | null              # For sample runs
  total_patients: int
  is_cancelled: bool (default false)
  result_summary: JSON                 # Aggregate stats after completion
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

  # Search results
  notes_searched: int (default 0)
  notes_matched: int (default 0)

  # Classification results
  finding_label: str | null            # positive | negative | inconclusive | no_match
  finding_reasoning: str | null
  finding_evidence: JSON | null        # note_ids, matched excerpts
  predicted_score: float | null
  token_usage: JSON | null             # {prompt_tokens, completion_tokens}
  error_message: str | null

  started_at, completed_at: datetime
  INDEX: (pipeline_run_id, status)     # For worker queue pulls with SKIP LOCKED
```

### Evidence

```
Evidence:
  id: UUID (PK)
  patient_task_id: bigint (FK)
  note_id: UUID (FK)
  text: str                            # The matched excerpt
  start_pos: int                       # Character offset in note.text
  end_pos: int                         # Character offset end
  match_source: str                    # "keyword" | "regex" | "exclusion_match"
  match_pattern: str | null            # The pattern that matched
```

### Annotation (patient-level)

```
Annotation:
  id: UUID (PK)
  project_id, patient_id: UUID (FK)
  pipeline_run_id: UUID (FK)
  patient_task_id: bigint (FK)

  # Classification result
  predicted_label: str                 # positive | negative | inconclusive
  predicted_reasoning: str
  predicted_score: float | null

  # Human review
  review_status: pending | confirmed | rejected | skipped
  reviewer_label: str | null
  event_date: date | null
  reviewer_notes: str | null
  reviewed_by: UUID (FK) | null
  reviewed_at: datetime | null
  created_at: datetime
```

### Models removed/replaced

- `SearchQuery` → merged into `EventConfig.search_patterns` (LLM-generated)
- `PredictorConfig` → merged into `EventConfig`
- `NlpJob` → replaced by `PipelineRun`
- Separate NLP and PREDICTION BackgroundJob types → single PIPELINE type
- Sentence-level `Annotation` → patient-level `Annotation` with `Evidence` records

### Models unchanged

- `Patient`, `Note` — unchanged
- `Sentence` — still created by search (but as Evidence records, not a separate model)
- `BackgroundJob` — still used for INGESTION and EXPORT job types

## Pipeline Flow

### Unified Workflow

```
1. CONFIGURE (Event Config Page)
   ├── Clinician describes event in natural language
   ├── LLM generates search patterns (keywords, regex, exclusions)
   ├── Clinician reviews generated patterns
   ├── Configure LLM (provider, model)
   └── Iterate until patterns look right

2. RUN SAMPLE (same page)
   ├── PipelineRun(run_type="sample", sample_size=N)
   ├── Picks N random patients → creates PatientTasks
   ├── Per patient: search notes → classify matched notes (1 LLM call)
   ├── Creates Evidence records and Annotations
   └── Shows results: match stats + classification results

3. REVIEW & CALIBRATE
   ├── Clinician reviews sample findings (confirm/reject each)
   ├── System computes precision/recall/F1 from reviews
   ├── Shows metrics at different score thresholds
   ├── Clinician can refine description and re-run sample
   └── Clinician "commits" the config (locks everything)

4. RUN FULL PIPELINE
   ├── PipelineRun(run_type="full")
   ├── Creates PatientTask for ALL patients (sample already done)
   ├── Workers pull patients via SKIP LOCKED
   ├── Per patient: search → classify if matched → create annotation
   ├── Progress: WebSocket (patients completed / total)
   └── Results available for annotation immediately per-patient

5. ANNOTATE
   ├── Patient-first review: classification + evidence excerpts
   ├── Annotator sees highlighted evidence in full note context
   ├── Predictions below calibrated threshold hidden by default
   └── Confirm/reject with optional event date and notes
```

### Cost Estimation

After the sample run, the system can extrapolate:
- Match rate from sample → estimated matched notes in full corpus
- Avg tokens per matched note from sample → estimated total tokens
- Provider pricing → estimated cost

```
Sample (50 patients): 12% match rate, avg 1,800 tokens/note
Full corpus (100K patients, 500K notes):
  Estimated matches: 60,000 notes
  Estimated tokens: 108M
  Estimated cost (GPT-4o-mini batch): ~$27
```

## Scaling

### Worker Parallelism

Multiple ARQ workers process patients concurrently:

```sql
SELECT id, patient_id FROM patient_task
WHERE pipeline_run_id = :run_id AND status = 'queued'
ORDER BY id LIMIT 1
FOR UPDATE SKIP LOCKED
```

Each worker: pull patient → search notes → classify → commit → next.

### Batch API Support (Phase 2 optimization)

For full runs, instead of per-patient LLM calls, collect all matched notes and submit via batch API (OpenAI Batch, Anthropic Batches). This provides:
- 50% cost reduction (OpenAI Batch pricing)
- No rate limits
- Higher throughput

The PatientTask model supports this: batch submission creates tasks in `processing` state, batch completion callback updates them to `completed`.

### Concurrent Classification per Patient

For patients with multiple matched notes, classify concurrently:

```python
results = await asyncio.gather(*[
    classify_note(note, event_config)
    for note in matched_notes
])
```

### Cancellation

- `PipelineRun.is_cancelled = True` → workers check before each patient
- Current patient completes, then stops
- Unprocessed PatientTasks remain `queued`

### Retry

- **Retry failed**: `UPDATE patient_task SET status = 'queued' WHERE status = 'failed'`
- **Retry stalled**: Reset `processing` tasks older than timeout back to `queued`
- Granular: retry individual patients or all failures

## Annotation Interface

### Patient-first review

```
Patient List (filtered by predicted_label + calibrated threshold)
  └── Patient Card
        ├── Classification: "Positive — Myocardial Infarction"
        ├── Reasoning: "Troponin elevated at 2.4, ECG shows ST elevation..."
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

When annotator expands a note, evidence spans are highlighted using `start_pos`/`end_pos` from the Evidence model.

### Filtering

- Predictions below the calibrated confidence threshold are hidden by default
- Filter by predicted label (positive/negative/inconclusive)
- Annotator can adjust threshold to see more/fewer results

## Job Dashboard

New page at `/projects/:id/jobs` showing all pipeline runs and background jobs.

### Pipeline runs table

| Run | Type | Status | Progress | Patients | Matched | Started | Actions |
|-----|------|--------|----------|----------|---------|---------|---------|
| #12 | Full | Running | 2,450 / 10,000 | 24.5% | 310 | 5 min ago | Cancel |
| #11 | Sample | Completed | 50 / 50 | 100% | 8 | 1 hr ago | View |

### Expandable detail per run

- Patient task breakdown: completed / failed / skipped / queued / no_match
- Failed patients list with error messages + individual retry
- Token usage summary (prompt, completion, total)
- Config snapshot (patterns, LLM, threshold)
- Match rate and extrapolated cost

### Actions

- **Cancel**: Sets `is_cancelled=true`, workers stop after current patient
- **Retry failed**: Re-queues all `status=failed` patient tasks
- **Retry stalled**: Re-queues `processing` tasks older than timeout

## What Gets Removed

- Separate "Run NLP" and "Run Predictions" buttons/flows
- Manual regex writing by clinician (LLM generates from natural language)
- `NlpJob` model
- NLP and PREDICTION `BackgroundJob` types
- Sentence-level annotation workflow
- Separate `SearchQuery` and `PredictorConfig` configuration UIs

## Future Considerations (deferred)

- **Prompt caching**: Anthropic/OpenAI cache headers for shared system prompts across notes
- **Server-side batch APIs**: OpenAI Batch API (50% cheaper), Anthropic Message Batches. Design supports this — PatientTask status model is compatible with async batch workflows.
- **Per-patient agent deep-dive**: For inconclusive/low-confidence patients, run a full multi-round agent loop. The tiered approach: batch classify most patients cheaply, agent-investigate the hard cases.
- **Sandboxed code execution**: Future agent tool for complex data transformations
- **Additional search tools**: Date range filters, lab value extraction, structured data queries
