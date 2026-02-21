FROM python:3.12-slim AS builder

# Install build dependencies for packages like gevent, nmslib
RUN sed -i 's/http:/https:/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libc-dev \
    libffi-dev \
    make \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3

WORKDIR /app

# Install dependencies (cached layer) - model downloads cached in /root/.cache/uv
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=.python-version,target=.python-version \
    uv sync --frozen --no-install-project --no-dev

# Copy app and install project (separate layer so deps stay cached)
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace

FROM python:3.12-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus-multiproc

# Create the directory for Prometheus multiprocess metrics
RUN mkdir -p /tmp/prometheus-multiproc

COPY --from=builder /app /app
WORKDIR /app

EXPOSE 5001

CMD ["gunicorn", "app.wsgi:app", "--log-level", "debug"]
