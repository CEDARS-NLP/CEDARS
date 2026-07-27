FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev
# Fail the build early if the scispaCy clinical model is missing its lemmatizer
# or parser (the components the v1 NLP + negation logic depends on).
RUN uv run python -c "import spacy; nlp = spacy.load('en_core_sci_lg'); assert nlp.has_pipe('lemmatizer') and nlp.has_pipe('parser'), nlp.pipe_names; print('spaCy model OK:', nlp.pipe_names)"
COPY . .
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
