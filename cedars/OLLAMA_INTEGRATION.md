# Ollama Integration for CEDARS

This document describes how to use Ollama endpoints alongside the existing PINES architecture in CEDARS.

## Overview

CEDARS now supports processing medical notes using either:
- **PINES** (existing Hugging Face model endpoint)
- **Ollama** (local or remote Ollama server)
- **Auto-detection** (tries PINES first, falls back to Ollama)

## Configuration

### Environment Variables

Set these environment variables to configure Ollama:

```bash
# Required: Ollama server URL
export OLLAMA_API_URL="http://localhost:11434"

# Optional: Ollama model name (defaults to "llama2")
export OLLAMA_MODEL="llama3:8b"

# Optional: Force specific endpoint
export PREDICTION_ENDPOINT="ollama"  # or "pines" or "auto"
```

### Endpoint Selection Priority

1. **Explicit parameter**: `endpoint_type` parameter in function calls
2. **Environment variable**: `PREDICTION_ENDPOINT`
3. **Auto-detection**: Tries PINES first, then Ollama

## Usage

### Basic Usage (No Code Changes Required)

Once environment variables are set, CEDARS will automatically use Ollama:

```bash
# Set up Ollama
export OLLAMA_API_URL="http://localhost:11434"
export OLLAMA_MODEL="llama3:8b"
export PREDICTION_ENDPOINT="ollama"

# Run CEDARS as usual
python -m gunicorn -c gunicorn.conf.py app.wsgi:create_app()
```

### Advanced Usage (Custom Prompts)

For custom prompts, you can call the functions directly:

```python
from app.db import get_ollama_prediction, predict_and_save

# Custom prompt for specific medical condition
custom_prompt = """
Analyze this medical note for signs of heart failure.
Look for: shortness of breath, fluid retention, cardiac abnormalities.

Medical Note:
{note}

Score (0.0-1.0 where 1.0 = definite heart failure):
"""

# Use custom prompt
score = get_ollama_prediction(note_text, prompt=custom_prompt)

# Or use in batch processing
predict_and_save(
    text_ids=["note1", "note2"],
    prompt=custom_prompt,
    endpoint_type="ollama"
)
```

## Functions Modified

### New Functions

- `load_ollama_url()` - Loads Ollama configuration
- `get_ollama_prediction(note, prompt=None)` - Gets prediction from Ollama
- `get_prediction_unified(note, prompt=None, endpoint_type=None)` - Unified prediction routing

### Updated Functions

- `predict_and_save()` - Added `prompt` and `endpoint_type` parameters
- `process_patient_pines()` - Added `prompt` and `endpoint_type` parameters

### Backward Compatibility

All existing PINES functionality remains unchanged:
- `get_prediction()` - Still works for PINES
- `load_pines_url()` - Still works for PINES configuration
- Existing API calls work without modification

## Ollama Server Setup

### Local Installation

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a medical model (or general model)
ollama pull llama3:8b

# Start server (runs on localhost:11434 by default)
ollama serve
```

### Remote Server

```bash
# Configure for remote Ollama server
export OLLAMA_API_URL="http://your-server:11434"
export OLLAMA_MODEL="your-model-name"
```

## Prompt Engineering

The default prompt asks for medical case classification. You can customize it:

```python
# Example: Specific condition detection
prompt = """
Analyze this note for {condition} indicators.
Clinical criteria: {criteria}

Note: {note}

Confidence score (0.0-1.0):
"""

# Example: Multi-class classification
prompt = """
Classify this medical note:
0.0-0.2: Not relevant
0.2-0.4: Possible case  
0.4-0.6: Probable case
0.6-0.8: Likely case
0.8-1.0: Definite case

Note: {note}

Score:
"""
```

## Error Handling

The system handles common error scenarios:

- **Ollama server unavailable**: Falls back to PINES if `endpoint_type="auto"`
- **Invalid response**: Logs warning, defaults to 0.5 score
- **Parsing errors**: Attempts multiple parsing strategies
- **Network timeouts**: Uses 3600-second timeout (same as PINES)

## Performance Considerations

- **Ollama**: Generally slower than PINES, but more flexible
- **PINES**: Faster, optimized for medical classification
- **Auto mode**: Adds fallback overhead but provides reliability

## Monitoring

Both endpoints log their activity:

```
INFO: Got Ollama prediction for note: Patient presents... with score: 0.85
INFO: Got prediction for note: Patient presents... with score: 0.92
```

Review logs to monitor which endpoint is being used and performance.