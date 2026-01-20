# .env Configuration for PINES Hybrid Mode

## Add These Lines to Your `.env` File

Copy and paste this into your `.env` file in the CEDARS root directory:

```env
# ==================================================
# PINES Hybrid Configuration
# ==================================================

# Original PINES (Fine-tuned BERT models)
PINES_API_URL1=http://pines:8036
PINES_WORKERS=2

# PINES-LLM (LLM-based clinical event detection)
PINES_API_URL2=http://pines-llm:8036

# PINES Mode Configuration
# Options: "primary", "llm", or "both"
#   - "primary": Use only original PINES (BERT, fast, needs training)
#   - "llm":     Use only PINES-LLM (slower, no training needed, flexible)
#   - "both":    Enable hybrid mode (requires code to route specific notes)
PINES_MODE=llm

# Backward compatibility (fallback if PINES_MODE not recognized)
PINES_API_URL=http://pines-llm:8036
```

---

## Quick Start

### To Use PINES-LLM Only (Recommended for VTE Detection):
```env
PINES_MODE=llm
```

### To Use Original PINES Only:
```env
PINES_MODE=primary
```

### To Enable Both (Advanced):
```env
PINES_MODE=both
```

---

## Complete Example `.env` File

```env
# Database
DB_PORT=27017
DB_HOST_PORT=27018
DB_USER=admin
DB_PWD=password

# MinIO
MINIO_HOST=minio
MINIO_PORT=9000
MINIO_ACCESS_KEY=root
MINIO_SECRET_KEY=rootpassword
MINIO_VERSION=RELEASE.2024-05-10T01-41-38Z

# Redis
REDIS_PORT=6379

# Workers
WORKER_SCALE=2
GPU_SCALE=1

# Environment
ENV=dev

# ==================================================
# PINES Hybrid Configuration
# ==================================================
PINES_API_URL1=http://pines:8036
PINES_WORKERS=2
PINES_API_URL2=http://pines-llm:8036
PINES_MODE=llm
PINES_API_URL=http://pines-llm:8036
```

---

## After Updating .env

```bash
# Restart CEDARS to apply changes
docker-compose restart web worker-task

# Or restart everything
docker-compose down
docker-compose --profile cpu up -d
```

