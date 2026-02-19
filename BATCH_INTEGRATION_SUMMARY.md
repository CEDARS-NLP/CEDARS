# Batch Inference Integration - Summary

## What Was Changed (Minimal Modifications)

### File 1: `cedars/app/db.py`

#### Modified: `predict_and_save()` function (line ~2085)
```python
def predict_and_save(...):
    # Added check for batch mode
    use_batch = predictor_config.get("llm_config", {}).get("use_batch", False)
    
    if use_batch:
        # Collect notes for batch (don't predict yet)
        _save_notes_for_batch_processing(notes_for_batch)
    else:
        # Existing real-time logic unchanged
        prediction = get_prediction(note.text)
        pines_collection.insert_one(...)
```

#### Added 3 new functions:
1. `_save_notes_for_batch_processing()` - Save to BATCH_PENDING collection
2. `get_batch_pending_notes()` - Get pending notes after spacy
3. `submit_batch_job_for_pending_notes()` - Submit batch job to Bedrock
4. `import_batch_results_to_pines()` - **Import results to PINES collection** ← Key!

### File 2: `cedars/app/ops.py`

#### Modified: `callback_job_success()` (line ~539)
```python
def callback_job_success(...):
    if all_tasks_complete:
        # Check batch mode
        if use_batch:
            db.submit_batch_job_for_pending_notes()  # Submit batch job
```

#### Modified: LLM config save (line ~459)
```python
llm_config = {
    ...
    "use_batch": use_batch if llm_provider == "bedrock" else False,
}
```

#### Added 2 new routes:
1. `/batch_job_status` - View batch job status
2. `/import_batch_results` - Import results to PINES collection

### File 3: `cedars/app/templates/ops/upload_query.html`

- Added batch mode checkbox (only shows for Bedrock)
- Added JavaScript to show/hide based on provider

### File 4: `cedars/app/predictors/batch_bedrock.py`

- Modified `parse_results()` to return score (0.0-1.0) not binary label

### File 5: `cedars/app/templates/ops/batch_job_status.html` (NEW)

- Simple status page for batch jobs
- "Import Results" button

---

## The Workflow

```
1. User configures LLM + enables batch checkbox
   └─> Saved: llm_config.use_batch = true

2. User uploads notes → Click Submit
   └─> ops.py: do_nlp_processing()

3. SpaCy processing (unchanged)
   └─> For each patient: enqueue jobs
   └─> Workers run: nlpprocessor.automatic_nlp_processor()
   └─> SpaCy keyword matching happens ✅

4. Prediction phase (MODIFIED):
   └─> db.predict_and_save(matched_notes)
       ├─> If batch mode:
       │   └─> Save to BATCH_PENDING (no prediction yet)
       └─> If real-time:
           └─> get_prediction() → LLM call
           └─> Save to PINES collection ✅

5. After all patients processed:
   └─> ops.py: callback_job_success()
       └─> If batch mode:
           └─> db.submit_batch_job_for_pending_notes()
               ├─> Get pending notes from BATCH_PENDING
               ├─> Create JSONL files
               ├─> Upload to S3 (+ MinIO)
               └─> Submit to Bedrock ✅

6. Hours later, user clicks "Import Results":
   └─> ops.py: import_batch_results()
       ├─> Download from S3
       ├─> Parse results
       └─> db.import_batch_results_to_pines(results_df)
           └─> Save to PINES collection ✅✅✅
               (SAME format as real-time!)
```

---

## Key Points

✅ **Minimal changes** - Only modified `predict_and_save()` branching logic  
✅ **SpaCy first** - Matching happens before batch decision  
✅ **Same collection** - Batch results go to PINES collection  
✅ **Same format** - `predicted_score` field matches real-time  
✅ **Existing code unchanged** - Real-time workflow untouched  

## Result Data Format (PINES Collection)

Both real-time and batch save to PINES collection with identical structure:

```python
{
    "text_id": "note_123",
    "text": "Patient has DVT...",
    "text_date": "2024-01-01",
    "patient_id": "patient_456",
    "predicted_score": 0.95,  # ← 0.0 to 1.0 (same for both!)
    "report_type": "Progress Note",
    "document_type": "Clinical Note",
    # Batch-specific fields (optional):
    "batch_inference": true,
    "imported_at": datetime(...)
}
```

## No Separate Workflow!

The batch mode is just a different implementation of `predict_and_save()`:
- **Real-time**: Calls `get_prediction()` immediately
- **Batch**: Defers to batch job, imports later

Everything else (SpaCy, patient review, UI) works identically! 🎯
