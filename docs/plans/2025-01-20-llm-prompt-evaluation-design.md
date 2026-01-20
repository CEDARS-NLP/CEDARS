# LLM Prompt Evaluation System Design

## Overview

A prompt evaluation system that lets clinicians validate LLM performance on a sample before running predictions on all clinical notes. This addresses the challenge of low event prevalence (2-10%) by using stratified sampling to ensure both positive and negative examples are reviewed.

## User Workflow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  1. SAMPLING    │ ──► │  2. REVIEW      │ ──► │  3. VALIDATION  │
│                 │     │                 │     │                 │
│ Configure       │     │ Run LLM on      │     │ View metrics    │
│ keywords &      │     │ sample, review  │     │ Save validated  │
│ sample size     │     │ each prediction │     │ prompt or iterate│
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

1. Admin navigates to `/project/<id>/evaluation`
2. Configures keyword-based stratified sampling
3. System runs LLM predictions on sample (background job)
4. Admin reviews predictions one-by-one, marking correct/wrong/skip
5. Views metrics dashboard with drill-down into disagreements
6. Saves validated prompt (or iterates on event definition)
7. Later triggers full processing using the validated prompt

## Access Control

- **Evaluation page:** Project admins only
- **Review interface:** Project admins only
- **Metrics dashboard:** Project admins only

## Sampling Mechanism

Since LLM and PINES are mutually exclusive predictors, sampling uses keyword matching derived from the event definition.

### Stratified Sampling Strategy

```
Total Sample (e.g., 100 notes)
├── Keyword-match bucket (50%): Notes containing event keywords
└── No-match bucket (50%): Notes without keyword matches
```

### Keyword Source

Keywords extracted from `EventDefinition.include_criteria` field. Admin can also manually specify additional keywords on the evaluation page.

**Example:** For "Myocardial Infarction" with include_criteria "Positive troponin, ECG changes, chest pain":
- Keywords: `["troponin", "ECG", "chest pain", "MI", "infarction"]`
- Match bucket: Notes containing any of these terms
- No-match bucket: Random sample from remaining notes

### UI Controls

- Sample size slider (default: 50, range: 20-200)
- Bucket split ratio (default: 50/50, adjustable)
- Editable keyword list (pre-populated from event definition)
- Preview count: "Found X notes with keywords, Y without"

## Review Interface

After sampling, the admin reviews LLM predictions one by one to judge correctness.

```
┌─────────────────────────────────────────────────────────────┐
│  Evaluation Review                        [Progress: 12/50] │
├─────────────────────────────────────────────────────────────┤
│  Note ID: N-12345                                           │
│  Patient: P-001                                             │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Clinical Note Text                                   │   │
│  │ "Patient presented with acute chest pain. Troponin  │   │
│  │ elevated at 2.5. ECG shows ST elevation in V1-V4.   │   │
│  │ Diagnosed with STEMI..."                            │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  LLM Prediction:  ● POSITIVE  (confidence: 0.92)           │
│  Reasoning: "Note documents confirmed STEMI with elevated  │
│  troponin and ECG changes meeting include criteria."       │
│                                                             │
│  Is this prediction correct?                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ ✓ Correct│  │ ✗ Wrong  │  │ ? Skip   │                  │
│  └──────────┘  └──────────┘  └──────────┘                  │
│                                                             │
│  [← Previous]                              [Next →]         │
└─────────────────────────────────────────────────────────────┘
```

### Stored Per Judgment

- `note_id`, `evaluation_session_id`
- `llm_prediction` (label, score, reasoning)
- `clinician_judgment` (correct / wrong / skipped)
- `judged_by`, `judged_at`

## Metrics Dashboard

After reviewing samples, the dashboard shows aggregate metrics with drill-down capability.

### Summary Metrics Panel

```
┌─────────────────────────────────────────────────────────────┐
│  Evaluation Results - Session: 2024-01-20 14:30            │
│  Prompt: "Myocardial Infarction v2"        [Export CSV]     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Reviewed: 48/50    Correct: 41    Wrong: 7    Skipped: 2  │
│                                                             │
│  ┌───────────┬───────────┬───────────┬───────────┐         │
│  │ Accuracy  │ Precision │ Recall    │ F1 Score  │         │
│  │   85.4%   │   88.2%   │   81.0%   │   84.4%   │         │
│  └───────────┴───────────┴───────────┴───────────┘         │
│                                                             │
│  Confusion Matrix:                                          │
│              │ Clinician: Pos │ Clinician: Neg │            │
│  ────────────┼────────────────┼────────────────│            │
│  LLM: Pos    │      15 (TP)   │      3 (FP)    │            │
│  LLM: Neg    │       4 (FN)   │     26 (TN)    │            │
│                                                             │
│  Breakdown by confidence:                                   │
│  • High (>0.8):   92% accuracy (25/27)                     │
│  • Medium (0.5-0.8): 78% accuracy (14/18)                  │
│  • Low (<0.5):    67% accuracy (2/3)                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Drill-Down Panel

Shows list of all disagreements (wrong predictions) with ability to click and view:
- Full note text
- LLM reasoning
- Clinician judgment

This helps identify patterns in failures (e.g., LLM missing negations, misinterpreting family history).

## Validated Prompt Storage

After satisfactory evaluation, the admin saves the prompt configuration as "validated" for later use.

### Validation UI

```
┌─────────────────────────────────────────────────────────────┐
│  Prompt Validation                                          │
├─────────────────────────────────────────────────────────────┤
│  Current metrics meet your requirements?                    │
│                                                             │
│  Prompt version name: [myocardial_infarction_v2    ]       │
│  Notes (optional):    [Tuned for STEMI detection   ]       │
│                                                             │
│  ┌─────────────────┐     ┌─────────────────┐               │
│  │ Save as Valid   │     │ Continue Tuning │               │
│  └─────────────────┘     └─────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

### Storage Schema

When admin later triggers full processing (from project settings or ops page), the system uses the active validated prompt.

## Data Model

### `evaluation_sessions` Collection

```python
{
    "_id": ObjectId,
    "project_id": str,
    "created_by": str,  # user_id
    "created_at": datetime,
    "status": str,  # "sampling" | "running" | "reviewing" | "completed"

    # Sampling config
    "sample_config": {
        "size": 50,
        "keyword_match_ratio": 0.5,
        "keywords": ["troponin", "ECG", "chest pain"],
    },
    "sampled_note_ids": [str],  # Note IDs selected

    # LLM config used for this session
    "llm_config": {
        "provider": "ollama",
        "model": "llama3",
        "api_base": "http://localhost:11434",
        "temperature": 0.0,
        "timeout": 60
    },
    "event_definition": {
        "name": "Myocardial Infarction",
        "description": "Confirmed heart attack",
        "include_criteria": "Positive troponin, ECG changes",
        "exclude_criteria": "Rule-out, family history"
    },

    # Computed metrics (updated as reviews complete)
    "metrics": {
        "reviewed": 48,
        "correct": 41,
        "wrong": 7,
        "skipped": 2,
        "accuracy": 0.854,
        "precision": 0.882,
        "recall": 0.810,
        "f1": 0.844
    }
}
```

### `evaluation_judgments` Collection

```python
{
    "_id": ObjectId,
    "session_id": ObjectId,
    "note_id": str,
    "note_text": str,  # Stored for audit trail
    "llm_prediction": {
        "label": 1,
        "score": 0.92,
        "reasoning": "Note documents confirmed STEMI with elevated troponin..."
    },
    "judgment": str,  # "correct" | "wrong" | "skipped"
    "judged_by": str,
    "judged_at": datetime
}
```

### `validated_prompts` Collection

```python
{
    "_id": ObjectId,
    "project_id": str,
    "version_name": str,  # e.g., "myocardial_infarction_v2"
    "notes": str,  # Optional admin notes
    "event_definition": {
        "name": "Myocardial Infarction",
        "description": "...",
        "include_criteria": "...",
        "exclude_criteria": "..."
    },
    "llm_config": {
        "provider": "ollama",
        "model": "llama3",
        ...
    },
    "evaluation_metrics": {
        "accuracy": 0.854,
        "precision": 0.882,
        "recall": 0.810,
        "f1": 0.844,
        "sample_size": 48
    },
    "evaluation_session_id": ObjectId,  # Reference to source session
    "validated_by": str,
    "validated_at": datetime,
    "is_active": bool  # Only one active per project
}
```

## Implementation Structure

### New Files

```
app/
├── evaluation/
│   ├── __init__.py           # Blueprint registration
│   ├── routes.py             # Routes: /project/<id>/evaluation/*
│   ├── service.py            # Business logic
│   └── models.py             # Pydantic models
├── repositories/
│   ├── interfaces/
│   │   └── evaluation_repository.py
│   └── mongo/
│       └── evaluation_repository.py
templates/
└── evaluation/
    ├── index.html            # Main evaluation page (sampling config)
    ├── review.html           # Note-by-note review interface
    └── dashboard.html        # Metrics dashboard
```

### Modified Files

| File | Change |
|------|--------|
| `app/__init__.py` | Register evaluation blueprint |
| `templates/project.html` | Add "Evaluation" link for admins |
| `app/ops.py` | Add "Use Validated Prompt" option when triggering full processing |

### Key Service Functions

**`evaluation/service.py`:**

```python
def create_session(project_id: str, sample_config: SampleConfig,
                   llm_config: LLMConfig, event_definition: EventDefinition) -> str:
    """Create evaluation session and sample notes using keyword stratification."""

def run_predictions(session_id: str) -> None:
    """Run LLM predictions on sampled notes (background RQ job)."""

def get_next_for_review(session_id: str) -> Optional[EvaluationItem]:
    """Get next un-reviewed note for the review interface."""

def record_judgment(session_id: str, note_id: str,
                    judgment: str, user_id: str) -> None:
    """Store clinician judgment and update session metrics."""

def compute_metrics(session_id: str) -> EvaluationMetrics:
    """Calculate accuracy, precision, recall, F1 from judgments."""

def get_disagreements(session_id: str) -> list[EvaluationItem]:
    """Get all items where LLM prediction was marked wrong."""

def validate_prompt(session_id: str, version_name: str,
                    notes: str, user_id: str) -> str:
    """Save current config as validated prompt, return prompt_id."""

def get_active_validated_prompt(project_id: str) -> Optional[ValidatedPrompt]:
    """Get the active validated prompt for a project."""
```

## Future Considerations

Not in scope for initial implementation, but worth noting:

1. **Prompt A/B testing:** Compare multiple prompt versions side-by-side
2. **Active learning:** After initial sample, suggest additional notes to review based on uncertainty
3. **Ongoing monitoring:** Track LLM vs clinician agreement during regular annotation (silent tracking mentioned in early discussion)
4. **Cost estimation:** Show estimated API cost before running predictions
