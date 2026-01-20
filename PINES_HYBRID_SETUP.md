# PINES Hybrid Setup Guide

This guide shows you how to run both PINES services (Original BERT + PINES-LLM) simultaneously in CEDARS.

## Overview

**Changes Made:**
1. ✅ Updated `docker-compose.yml` - Added Ollama and PINES-LLM services
2. ✅ Created `PINES-LLM/Dockerfile` - Containerized PINES-LLM
3. ✅ Updated `cedars/app/api.py` - Added hybrid mode support
4. ✅ Updated `cedars/app/db.py` - Added routing logic for both backends
5. ✅ Updated `PINES-LLM/llm_config.yaml` - Docker-compatible configuration

---

## Configuration

### Step 1: Update Your `.env` File

Add these lines to your `.env` file in the CEDARS root directory:

```env
# ==================================================
# PINES Hybrid Configuration
# ==================================================

# Original PINES (Fine-tuned BERT)
PINES_API_URL1=http://pines:8036
PINES_WORKERS=2

# PINES-LLM (LLM-based)
PINES_API_URL2=http://pines-llm:8036

# PINES Mode: Which backend(s) to use
# Options:
#   "primary" - Use only original PINES (URL1)
#   "llm"     - Use only PINES-LLM (URL2)
#   "both"    - Enable hybrid mode (route dynamically)
PINES_MODE=llm

# Backward compatibility (optional - fallback if PINES_MODE not working)
PINES_API_URL=http://pines-llm:8036
```

### Step 2: Choose Your Mode

**Mode 1: Use Only Original PINES (Fine-tuned BERT)**
```env
PINES_MODE=primary
```
- Fast predictions (~1-2 seconds)
- Requires training data
- Best for proven use cases

**Mode 2: Use Only PINES-LLM (Recommended for VTE)**
```env
PINES_MODE=llm
```
- Slower predictions (5-15 seconds on CPU, 2-5 on GPU)
- No training required
- Better for new tasks
- Works with prompts

**Mode 3: Hybrid - Use Both (Advanced)**
```env
PINES_MODE=both
```
- Route different notes to different backends
- Requires code modification to specify routing
- See "Advanced Usage" below

---

## Deployment

### For New EC2 Instance (Automated):

```bash
# 1. Clone repository
git clone https://github.com/your-org/CEDARS.git
cd CEDARS

# 2. Create .env file
cp .sample.env .env
nano .env
# Add the PINES configuration from above

# 3. Build services
docker-compose build

# 4. Start services (CPU profile)
docker-compose --profile cpu up -d

# 5. Wait for models to download (first time only, ~5-10 min)
docker-compose logs -f ollama-setup

# 6. Verify services
docker-compose ps
```

### For GPU Instance:

```bash
# Install NVIDIA Docker support first
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker

# Start with GPU profile
docker-compose --profile gpu up -d
```

---

## Testing

### Test 1: Check All Services Running

```bash
docker-compose ps

# Should show:
# - cedars_web_1
# - cedars_pines_1 (and pines_2 if PINES_WORKERS=2)
# - cedars-pines-llm
# - cedars-ollama
# - ... other services
```

### Test 2: Test Original PINES (from inside Docker)

```bash
docker exec cedars_web_1 curl -X POST http://pines:8036/predict \
  -H "Content-Type: application/json" \
  -d '{"text": "Patient diagnosed with DVT"}'
```

### Test 3: Test PINES-LLM (from inside Docker)

```bash
docker exec cedars_web_1 curl -X POST http://pines-llm:8036/predict \
  -H "Content-Type: application/json" \
  -d '{"text": "CT chest shows bilateral pulmonary emboli"}'
```

### Test 4: Test from Outside Docker

```bash
# Test PINES-LLM (exposed on port 8037)
curl -X POST http://localhost:8037/predict \
  -H "Content-Type: application/json" \
  -d '{"text": "CT shows PE"}'

# Test PINES-LLM health
curl http://localhost:8037/healthcheck
```

### Test 5: Upload Notes via CEDARS UI

1. Go to http://YOUR_EC2_IP
2. Login
3. Upload clinical notes
4. Check "Enable PINES" checkbox
5. Submit
6. Monitor logs:
```bash
docker-compose logs -f web worker-task pines-llm
```

---

## Advanced Usage

### Routing to Specific PINES Backend

If you set `PINES_MODE=both`, you can route individual notes to specific backends.

**In your CEDARS processing code:**

```python
# In cedars/app/nlpprocessor.py or wherever you call get_prediction

# Route to LLM for new/uncertain cases
score = db.get_prediction(note_text, use_llm=True)

# Route to primary/fine-tuned for proven cases
score = db.get_prediction(note_text, use_llm=False)

# Or route based on task type:
if task_type == "vte_detection":
    score = db.get_prediction(note_text, use_llm=True)  # Use LLM for VTE
else:
    score = db.get_prediction(note_text, use_llm=False)  # Use fine-tuned for others
```

### Switching Models in PINES-LLM

To use a different LLM model:

```bash
# 1. Pull new model
docker exec cedars-ollama ollama pull llama3.1:8b

# 2. Update config
nano PINES-LLM/llm_config.yaml
# Change: model_name: llama3.1:8b

# 3. Restart PINES-LLM
docker-compose restart pines-llm

# 4. Verify
curl http://localhost:8037/ | grep Model
```

**Model Recommendations:**
- `llama3.2:1b` - Fastest, lowest memory (1.3GB), good for testing
- `llama3.2:3b` - Balanced speed/accuracy (2GB)
- `llama3.1:8b` - Better accuracy (4.7GB), recommended for production
- `llama3.1:70b` - Best accuracy (40GB), requires GPU

---

## Monitoring

### View Logs

```bash
# All services
docker-compose logs -f

# Specific services
docker-compose logs -f pines-llm ollama
docker-compose logs -f pines
docker-compose logs -f web worker-task

# Last 100 lines
docker-compose logs --tail=100 pines-llm
```

### Resource Usage

```bash
# Monitor container resources
docker stats

# Check Ollama model usage
docker exec cedars-ollama ollama list
docker exec cedars-ollama ollama show llama3.2:1b
```

### Database Predictions

```bash
# Connect to MongoDB
docker exec -it cedars_db_1 mongosh -u admin -p password

# Check predictions
use cedars
db.PINES.find().limit(5).pretty()

# Count predictions
db.PINES.countDocuments()

# Find predictions by score
db.PINES.find({"predicted_score": {$gt: 0.95}}).count()
```

---

## Troubleshooting

### Problem: Ollama model not found

```bash
# Check models
docker exec cedars-ollama ollama list

# Pull model manually
docker exec cedars-ollama ollama pull llama3.2:1b

# Restart PINES-LLM
docker-compose restart pines-llm
```

### Problem: PINES-LLM slow

**For CPU instances:**
- Use smaller model: `llama3.2:1b`
- Reduce max_tokens in `llm_config.yaml`

**For GPU instances:**
- Verify GPU is being used:
```bash
docker logs cedars-ollama | grep -i gpu
docker exec cedars-ollama nvidia-smi
```
- Use GPU profile: `docker-compose --profile gpu up -d`

### Problem: Services can't connect

```bash
# Check network
docker network inspect cedars_cedars

# Check service names resolve
docker exec cedars_web_1 ping pines -c 2
docker exec cedars_web_1 ping pines-llm -c 2
docker exec cedars_web_1 ping ollama -c 2

# Check .env configuration
docker exec cedars_web_1 env | grep PINES
```

### Problem: Out of memory

```bash
# Check memory usage
docker stats

# Reduce limits in docker-compose.yml:
# pines-llm:
#   deploy:
#     resources:
#       limits:
#         memory: '1g'  # Reduce from 2g
```

**Or use a larger EC2 instance:**
- Minimum: t2.2xlarge (8 vCPU, 32GB RAM)
- Recommended: c6i.2xlarge (8 vCPU, 16GB RAM, better CPU)
- Best: g4dn.xlarge (4 vCPU, 16GB RAM, 1 GPU)

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│                   CEDARS Web App                    │
│                                                     │
│  Reads: PINES_MODE, PINES_API_URL1, PINES_API_URL2 │
└────────────────────┬────────────────────────────────┘
                     │
         ┌───────────┴────────────┐
         │                        │
         ▼                        ▼
┌─────────────────┐      ┌─────────────────┐
│  Original PINES │      │   PINES-LLM     │
│                 │      │                 │
│  Fine-tuned     │      │  Prompt-based   │
│  BERT Models    │      │  LLM Detection  │
│                 │      │                 │
│  Port: 8036     │      │  Port: 8036     │
│  (internal)     │      │  (8037 external)│
└─────────────────┘      └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │     Ollama      │
                         │                 │
                         │  LLM Inference  │
                         │  Engine         │
                         │                 │
                         │  Port: 11434    │
                         └─────────────────┘
```

---

## Performance Comparison

| Metric | Original PINES | PINES-LLM (CPU) | PINES-LLM (GPU) |
|--------|---------------|-----------------|-----------------|
| Latency | 1-2 seconds | 10-30 seconds | 2-5 seconds |
| Setup | Requires training | No training | No training |
| Accuracy | High (trained) | Very high | Very high |
| Flexibility | Low (fixed) | High (prompts) | High (prompts) |
| Cost | Low | Medium | Medium-High |

---

## Next Steps

1. ✅ Test both services
2. ✅ Upload sample notes through CEDARS
3. ✅ Evaluate prediction quality
4. ✅ Tune prompts in `PINES-LLM/prompts/vte_prompt.yaml`
5. ✅ Monitor performance and adjust resources
6. ✅ Consider GPU instance for production if using LLM extensively

---

## Support

For issues:
1. Check logs: `docker-compose logs -f`
2. Check this troubleshooting section
3. Review CEDARS and PINES documentation
4. File an issue on GitHub

---

**You now have a fully hybrid PINES deployment!** 🎉

Both services are running simultaneously, and you can switch between them by changing `PINES_MODE` in your `.env` file.

