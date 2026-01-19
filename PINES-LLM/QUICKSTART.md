# PINES-LLM Quick Start Guide

Get up and running with LLM-based clinical event detection in 5 minutes.

## Prerequisites

- Python 3.9+ OR Docker
- 8GB+ RAM (for small models)
- 40GB+ VRAM for larger models (optional)

## 🚀 Method 1: Ollama (Recommended for First Try)

### Step 1: Install Ollama

**Windows:**
Download from https://ollama.com/download/windows

**Mac:**
```bash
brew install ollama
```

**Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### Step 2: Pull Llama Model

```bash
# Small model (4GB, fast)
ollama pull llama3.1:8b

# OR Large model (40GB, more accurate)
ollama pull llama3.1:70b
```

### Step 3: Start Ollama

```bash
ollama serve
```

Keep this terminal open.

### Step 4: Install PINES-LLM

Open a new terminal:

```bash
cd PINES-LLM
pip install -r requirements.txt
```

### Step 5: Start PINES-LLM

```bash
python llm_pines.py
```

### Step 6: Test It!

Open another terminal:

```bash
# Test VTE detection
curl -X POST http://localhost:8036/predict \
  -H "Content-Type: application/json" \
  -d '{"text": "Patient with acute DVT left leg confirmed by ultrasound."}'
```

**Expected output:**
```json
{
  "prediction": {"label": 1, "score": 0.96},
  "model": "llama3.1:8b",
  "metadata": {
    "reasoning": "Confirmed acute DVT with imaging",
    "latency_ms": 1250
  }
}
```

✅ **You're done!** PINES-LLM is running.

---

## 🐳 Method 2: Docker (All-in-One)

```bash
cd PINES-LLM

# Start everything (Ollama + PINES-LLM)
docker-compose --profile ollama up -d

# Wait for model download (first time only, ~5 minutes)
docker-compose logs -f llm-pines

# Test
curl http://localhost:8036/healthcheck
```

---

## 🔗 Integrate with CEDARS

### Option A: Update Environment Variable

In your CEDARS `.env` file:

```bash
PINES_API_URL=http://localhost:8036
```

Restart CEDARS. Done!

### Option B: Replace in Docker Compose

In your main `docker-compose.yml`, modify the `pines` service:

```yaml
services:
  pines:
    build:
      context: ./PINES-LLM  # Changed from ./PINES
    # ... rest stays same
```

```bash
docker-compose up -d pines
```

---

## 🎯 Common Use Cases

### Use Case 1: VTE Detection

```python
import requests

note = """
Patient presents with left leg swelling and pain.
Ultrasound reveals acute DVT in left popliteal vein.
Started on anticoagulation therapy.
"""

response = requests.post(
    "http://localhost:8036/predict",
    json={"text": note, "task": "vte_detection"}
)

result = response.json()
print(f"Event detected: {result['prediction']['label']}")
print(f"Confidence: {result['prediction']['score']}")
```

### Use Case 2: Metastasis Detection

```python
note = """
CT chest/abdomen/pelvis shows multiple liver lesions
consistent with metastatic disease from known lung primary.
"""

response = requests.post(
    "http://localhost:8036/predict",
    json={"text": note, "task": "metastasis_detection"}
)
```

### Use Case 3: Batch Processing

```python
notes = [
    {"text": "Patient 1 note..."},
    {"text": "Patient 2 note..."},
    {"text": "Patient 3 note..."}
]

response = requests.post(
    "http://localhost:8036/predict_batch",
    json=notes
)
```

---

## ⚙️ Configuration

### Switch to Different Model

Edit `llm_config.yaml`:

```yaml
model_name: llama3.1:70b  # Use larger model
```

Restart service:

```bash
python llm_pines.py
```

### Adjust Temperature (Randomness)

```yaml
model_settings:
  temperature: 0.0  # Deterministic (recommended)
  # OR
  temperature: 0.3  # Slightly more creative
```

### Change Task

```bash
curl -X POST http://localhost:8036/predict \
  -d '{"text": "...", "task": "metastasis_detection"}'
```

---

## 🔍 Troubleshooting

### Problem: "Connection refused" error

**Solution:**
```bash
# Check Ollama is running
ollama list

# Start Ollama if not running
ollama serve
```

### Problem: "Model not found"

**Solution:**
```bash
# Pull the model
ollama pull llama3.1:8b

# Verify it's available
ollama list
```

### Problem: Slow responses (>10 seconds)

**Solutions:**
1. Use smaller model: `llama3.1:8b` instead of `70b`
2. Use GPU (Ollama auto-detects)
3. Switch to vLLM for production (see README.md)

### Problem: Low accuracy

**Solutions:**
1. Try larger model (`70b` instead of `8b`)
2. Adjust prompts in `prompts/` directory
3. Set `temperature: 0.0` for deterministic output

---

## 📚 Next Steps

1. **Test on sample data**: Try with your actual clinical notes
2. **Compare accuracy**: Run on labeled dataset vs. fine-tuned PINES
3. **Customize prompts**: Edit `prompts/vte_prompt.yaml` for your use case
4. **Scale up**: Move to vLLM with GPU for production
5. **Add new tasks**: Create custom prompt YAML files

---

## 🆘 Need Help?

- Check logs: `docker-compose logs llm-pines`
- Test backend: `curl http://localhost:11434/api/tags` (Ollama)
- Verify health: `curl http://localhost:8036/healthcheck`

---

**That's it!** You now have a working LLM-based clinical event detection system with zero training required. 🎉




