# Dockerfile for PINES-LLM service
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8036

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8036/healthcheck')" || exit 1

# Run the service
CMD ["uvicorn", "llm_pines:app", "--host", "0.0.0.0", "--port", "8036"]




