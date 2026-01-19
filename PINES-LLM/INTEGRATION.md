# Integrating PINES-LLM with CEDARS

This guide shows you how to integrate the LLM-based PINES service with your existing CEDARS installation.

## Overview

PINES-LLM is designed to be a **drop-in replacement** for the original PINES service. CEDARS expects a service at `/predict` endpoint that returns predictions in a specific format, which PINES-LLM fully supports.

## Integration Methods

### Method 1: Environment Variable (Easiest)

Simply point CEDARS to the LLM-PINES service using an environment variable.

**1. Start PINES-LLM:**

```bash
cd PINES-LLM
# Start Ollama first
ollama serve &
# Start PINES-LLM
python llm_pines.py
```

**2. Update CEDARS `.env` file:**

```bash
# Add or modify this line
PINES_API_URL=http://localhost:8036

# Or if running in Docker
PINES_API_URL=http://llm-pines:8036
```

**3. Restart CEDARS:**

```bash
docker-compose restart web
```

That's it! CEDARS will now use LLM-based predictions.

---

### Method 2: Docker Compose Integration

Modify your main `docker-compose.yml` to include PINES-LLM services.

**In your main CEDARS `docker-compose.yml`:**

```yaml
services:
  # Your existing CEDARS services...
  web:
    # ... existing config ...
    environment:
      - PINES_API_URL=http://llm-pines:8036
    depends_on:
      - llm-pines

  # Add Ollama service
  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_data:/root/.ollama
    networks:
      - cedars
    command: >
      sh -c "ollama serve &
      sleep 5 &&
      ollama pull llama3.1:8b &&
      wait"

  # Add LLM-PINES service
  llm-pines:
    build:
      context: ./PINES-LLM
    ports:
      - "8036:8036"
    networks:
      - cedars
    depends_on:
      - ollama
    restart: unless-stopped

volumes:
  ollama_data:

networks:
  cedars:
    driver: bridge
```

**Start everything:**

```bash
docker-compose up -d
```

---

### Method 3: Replace Original PINES

Replace the original PINES service entirely.

**In `docker-compose.yml`, modify the `pines` service:**

```yaml
services:
  # ... other services ...
  
  # Comment out or remove original PINES
  # pines:
  #   build:
  #     context: ./PINES
  #   ...
  
  # Replace with LLM-PINES (keep name as 'pines' for compatibility)
  pines:
    build:
      context: ./PINES-LLM
    networks:
      - cedars
    depends_on:
      - ollama
    profiles:
      - cpu
      - gpu
```

This maintains the service name `pines`, so CEDARS automatically discovers it.

---

## Verification

### 1. Check PINES-LLM is Running

```bash
curl http://localhost:8036/healthcheck
```

Expected response:
```json
{
  "status": "Healthy",
  "backend_healthy": true
}
```

### 2. Test Prediction

```bash
curl -X POST http://localhost:8036/predict \
  -H "Content-Type: application/json" \
  -d '{"text": "Patient diagnosed with DVT."}'
```

Expected response:
```json
{
  "prediction": {
    "label": 1,
    "score": 0.95
  },
  "model": "llama3.1:8b"
}
```

### 3. Check CEDARS Integration

Look at CEDARS logs to confirm it's calling PINES-LLM:

```bash
docker-compose logs -f web
```

You should see requests being made to the PINES API.

---

## Configuration

### Choosing a Model

Edit `PINES-LLM/llm_config.yaml`:

```yaml
# For fast testing (CPU friendly)
model_name: llama3.1:8b

# For better accuracy (needs GPU/more time)
model_name: llama3.1:70b
```

Restart the service after changes.

### Selecting Tasks

CEDARS can send different task types. Configure which prompt to use:

```yaml
# In llm_config.yaml
default_task: vte_detection  # or metastasis_detection, default, etc.
```

Or specify in the request from CEDARS (requires CEDARS modification):

```python
# In cedars/app/db.py, modify get_prediction()
data = {
    'text': note,
    'task': 'vte_detection'  # Add this line
}
```

### Adjusting Threshold

The original CEDARS code filters predictions based on a threshold (default 0.95).

**In `cedars/app/nlpprocessor.py`:**

```python
def process_patient_pines(self, patient_id: str, threshold: float = 0.95):
    # ...
    if score < threshold:
        # Skip this annotation (marked as reviewed)
    else:
        # Show to user
```

You can adjust this threshold for LLM predictions:

- Lower threshold (e.g., 0.90) → More annotations shown to users
- Higher threshold (e.g., 0.97) → Fewer annotations (only very confident)

---

## Performance Considerations

### Latency

LLM predictions are slower than fine-tuned models:

- **Fine-tuned BERT**: 100-500ms per note
- **Llama 3.1 8B (CPU)**: 5-15 seconds per note
- **Llama 3.1 8B (GPU)**: 1-3 seconds per note
- **Llama 3.1 70B (GPU)**: 0.5-2 seconds per note

**Recommendations:**
- For real-time annotation: Use Llama 8B on GPU
- For batch processing: Any size is fine
- For production: Use vLLM with Llama 70B on GPU

### Scaling

For high-volume use, deploy multiple PINES-LLM instances:

```yaml
services:
  llm-pines:
    # ... config ...
    deploy:
      replicas: 3
```

Add a load balancer (nginx) in front:

```yaml
services:
  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    ports:
      - "8036:80"
```

**nginx.conf:**
```nginx
upstream llm-pines {
    server llm-pines-1:8036;
    server llm-pines-2:8036;
    server llm-pines-3:8036;
}

server {
    listen 80;
    location / {
        proxy_pass http://llm-pines;
    }
}
```

---

## Hybrid Approach: Both Fine-tuned + LLM

Use fine-tuned models for proven tasks and LLM for new ones.

**Create a routing service (`PINES-LLM/hybrid_pines.py`):**

```python
from fastapi import FastAPI
import httpx

app = FastAPI()

FINETUNED_URL = "http://pines-finetuned:8036"
LLM_URL = "http://pines-llm:8036"

# Tasks that have fine-tuned models
FINETUNED_TASKS = ["vte_detection", "metastasis_detection"]

@app.post("/predict")
async def predict(request: dict):
    task = request.get("task", "default")
    
    # Route to fine-tuned if available
    if task in FINETUNED_TASKS:
        async with httpx.AsyncClient() as client:
            response = await client.post(FINETUNED_URL, json=request)
            return response.json()
    else:
        # Use LLM for new tasks
        async with httpx.AsyncClient() as client:
            response = await client.post(LLM_URL, json=request)
            return response.json()
```

---

## Monitoring

### Logs

Check PINES-LLM logs:

```bash
# Docker
docker-compose logs -f llm-pines

# Local
# Logs go to stdout by default
```

### Metrics

PINES-LLM returns metadata with each prediction:

```json
{
  "metadata": {
    "latency_ms": 1250,
    "tokens_used": 450,
    "reasoning": "..."
  }
}
```

Store these in CEDARS for analysis:

```python
# In cedars/app/db.py, modify predict_and_save()
pines_collection.insert_one({
    # ... existing fields ...
    "latency_ms": metadata.get("latency_ms"),
    "tokens_used": metadata.get("tokens_used"),
    "reasoning": metadata.get("reasoning")
})
```

---

## Troubleshooting

### Issue: CEDARS can't connect to PINES-LLM

**Check:**
1. Is PINES-LLM running? `curl http://localhost:8036/healthcheck`
2. Is the URL correct in `.env`?
3. Are they on the same Docker network?

**Fix for Docker networking:**
```yaml
# In docker-compose.yml, ensure same network
services:
  web:
    networks:
      - cedars
  llm-pines:
    networks:
      - cedars
```

### Issue: Predictions are too slow

**Solutions:**
1. Use smaller model: `llama3.1:8b`
2. Use GPU (Ollama auto-detects)
3. Switch to vLLM backend
4. Deploy multiple instances with load balancer

### Issue: Low accuracy

**Solutions:**
1. Try larger model: `llama3.1:70b`
2. Adjust prompts in `PINES-LLM/prompts/`
3. Set `temperature: 0.0` for deterministic output
4. Add few-shot examples to prompts

### Issue: Model not found in Ollama

```bash
# Pull the model
ollama pull llama3.1:8b

# Verify
ollama list
```

---

## Security Notes

- **PHI Protection**: All processing happens on your infrastructure
- **Network Isolation**: Run PINES-LLM on internal network only
- **No External Calls**: When using Ollama/vLLM (no PHI leaves your servers)
- **Audit Trail**: All predictions logged in CEDARS database

---

## Next Steps

1. **Test thoroughly**: Run on labeled dataset to validate accuracy
2. **Tune prompts**: Adjust prompts for your specific clinical scenarios
3. **Monitor performance**: Track latency and accuracy over time
4. **Consider hybrid**: Use fine-tuned for proven tasks, LLM for new ones
5. **Scale if needed**: Add more instances or switch to vLLM

---

Need help? Check the main README.md or contact the CEDARS team.




