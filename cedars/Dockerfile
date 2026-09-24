FROM ghcr.io/astral-sh/uv:0.12.18 AS uv
FROM python:3.12-slim AS builder

COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/.venv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM redis:7.2-alpine

COPY redis.conf /usr/local/etc/redis/redis.conf

CMD ["redis-server", "/usr/local/etc/redis/redis.conf", "--loglevel", "warning"]

FROM python:3.12-slim AS runtime

ENV VIRTUAL_ENV=/.venv \
    PATH="/.venv/bin:$PATH"

COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

WORKDIR /app
COPY . .
RUN mkdir -p /tmp/prometheus-multiproc
EXPOSE 8000

CMD [ "gunicorn", "-c", "gunicorn.conf.py", "app.main:app", "--log-level", "warning" ]
