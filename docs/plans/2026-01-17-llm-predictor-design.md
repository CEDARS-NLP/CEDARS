# LLM Predictor Integration Design

**Date:** 2026-01-17
**Branch:** `feature/llm-integration`
**Status:** Approved

## Problem

CEDARS currently uses PINES (a Longformer-based model) for clinical event classification. This requires training a separate NLP model for each clinical event type - expensive and time-consuming.

LLMs can classify clinical events using natural language descriptions, eliminating the need for custom-trained models per event.

## Goals

- Add LLM as an alternative to PINES for classification
- Support multiple LLM providers: OpenAI, Anthropic, Ollama, LMStudio, Gemini, Bedrock
- Maintain backwards compatibility with existing PINES workflow
- Per-project configuration (choose PINES or LLM)

## Non-Goals

- Replacing the keyword/spaCy filtering phase (kept as-is)
- Multi-tenant architecture (future work)
- Sentence-level classification (staying with document-level like PINES)

---

## Architecture

### Classification Flow

```
Notes → Keyword Filter → Notes with matching sentences
                              ↓
                    Send FULL NOTE to predictor
                              ↓
                    ┌─────────┴─────────┐
                    │                   │
                  PINES               LLM
            (whole document)    (whole document)
                    │                   │
                    └─────────┬─────────┘
                              ↓
                      Confidence Score
                              ↓
                   Score < threshold? → Auto-dismiss
                   Score ≥ threshold? → Human review
```

### Predictor Interface

A common interface so the system doesn't care which backend is used:

```python
# app/predictors/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class PredictionResult:
    score: float          # 0-1 confidence
    label: int            # 0 or 1
    model: str            # "pines-v1" or "gpt-4o" etc.
    reasoning: str | None # LLM can explain, PINES returns None

class BasePredictor(ABC):
    @abstractmethod
    def predict(self, text: str) -> PredictionResult:
        """Classify a clinical note. Returns score 0-1."""
        pass

    @abstractmethod
    def predict_batch(self, texts: list[str]) -> list[PredictionResult]:
        """Classify multiple notes."""
        pass

    @abstractmethod
    def healthcheck(self) -> bool:
        """Check if backend is available."""
        pass
```

### File Structure

**New files:**

```
cedars/app/
├── predictors/
│   ├── __init__.py
│   ├── base.py          # BasePredictor, PredictionResult
│   ├── pines.py         # PinesPredictor (wraps existing api.py logic)
│   ├── llm.py           # LLMPredictor (uses LiteLLM)
│   └── factory.py       # get_predictor(project_id)
├── models/
│   └── predictor_config.py  # Pydantic models for LLMConfig, EventDefinition
```

**Files to modify:**

| File | Changes |
|------|---------|
| `db.py` | Replace direct PINES calls with `get_predictor()` |
| `nlpprocessor.py` | Use predictor interface instead of `db.predict_and_save()` |
| `ops.py` | Add UI form fields, save predictor config to project |
| `api.py` | Keep as-is (PinesPredictor will use it internally) |
| `pyproject.toml` | Add `litellm` dependency |

---

## LLM Implementation

### LiteLLM

Using LiteLLM as unified interface to all LLM providers:

```toml
# pyproject.toml
[project.dependencies]
litellm = "^1.40"
```

LiteLLM handles:
- Authentication for each provider
- Rate limiting and retries
- Consistent API across providers
- Model name mapping (e.g., `openai/gpt-4o`, `ollama/llama3`)

### Prompt Template

Users provide event criteria, system generates full prompt:

**User provides:**
- Event name
- Description
- Include criteria
- Exclude criteria

**System generates:**

```
You are a clinical research assistant reviewing medical notes.

EVENT TO DETECT: {event_name}
DESCRIPTION: {event_description}
INCLUDE IF: {include_criteria}
EXCLUDE IF: {exclude_criteria}

CLINICAL NOTE:
---
{note_text}
---

INSTRUCTIONS:
1. Read the note carefully
2. Determine if this note documents the specified event
3. Consider: Is this a confirmed occurrence? Or is it negated,
   hypothetical, family history, or ruled-out?

Respond with JSON:
{
  "contains_event": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}
```

### Score Mapping

To match PINES behavior:
- `contains_event: true` → score = confidence
- `contains_event: false` → score = 1 - confidence

---

## Configuration

### Project Schema (MongoDB)

```python
{
  "_id": "project_123",
  "project_name": "MI Detection Study",
  "search_query": "myocardial infarction|heart attack|MI",

  # Existing PINES fields (kept for backwards compatibility)
  "nlp_apply": true,
  "pines_url": "http://pines:8036",

  # New fields
  "predictor_type": "llm",  # "pines" | "llm" | null
  "llm_config": {
    "provider": "openai",
    "model": "gpt-4o",
    "api_base": null,
    "api_key_env": "OPENAI_API_KEY"
  },
  "event_definition": {
    "name": "Myocardial Infarction",
    "description": "Confirmed heart attack diagnosis",
    "include_criteria": "Positive troponin, ECG changes, chest pain with confirmation",
    "exclude_criteria": "Rule-out, family history, hypothetical, past medical history"
  }
}
```

### Environment Variables

```bash
# .env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
AWS_ACCESS_KEY_ID=...      # For Bedrock
AWS_SECRET_ACCESS_KEY=...

# Local providers (no key needed)
OLLAMA_API_BASE=http://localhost:11434
LMSTUDIO_API_BASE=http://localhost:1234
```

### Backwards Compatibility

- If `predictor_type` is null/missing → defaults to current behavior
- Existing projects continue working without migration
- `api.py` functions unchanged - wrapped by PinesPredictor

---

## UI Changes

Below search query, extend existing NLP checkbox:

```
☑ Apply NLP classification
  ○ PINES (requires trained model)
  ○ LLM
      Provider: [OpenAI ▼]
      Model: [gpt-4o ▼]

      Event Definition:
      Name: [________________]
      Include if: [________________]
      Exclude if: [________________]
```

---

## Error Handling

```python
def predict(self, text: str) -> PredictionResult:
    try:
        response = litellm.completion(...)
        return self._parse_response(response)
    except litellm.AuthenticationError:
        raise PredictorError(f"Invalid API key for {self.provider}")
    except litellm.RateLimitError:
        raise PredictorError("Rate limit exceeded, try again later")
    except litellm.APIConnectionError:
        raise PredictorError(f"Cannot connect to {self.provider}")
    except json.JSONDecodeError:
        # LLM didn't return valid JSON - retry with stricter prompt
        return self._retry_with_json_reminder(text)
```

### Timeouts

- Default: 60 seconds per request
- Configurable per provider (local Ollama may need longer)
- PINES keeps existing 3600s timeout

---

## Testing Strategy

1. **Unit tests** for predictor interface
2. **Mock LiteLLM** responses in tests
3. **Integration tests** with Ollama (can run locally in CI)
4. **Existing PINES tests** unchanged

---

## Implementation Order

1. Create `predictors/` module with base interface
2. Implement `PinesPredictor` (wrap existing code)
3. Implement `LLMPredictor` with LiteLLM
4. Add factory function
5. Update `db.py` and `nlpprocessor.py` to use factory
6. Add UI form fields in `ops.py`
7. Add configuration storage
8. Write tests
