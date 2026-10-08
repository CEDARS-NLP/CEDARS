FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev
COPY . .
# Which commit this image was built from; shown by /api/v1/health. Pass --build-arg GIT_SHA=<sha>.
ARG GIT_SHA=unknown
ENV CEDARS_GIT_SHA=${GIT_SHA}
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
