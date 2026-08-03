#FROM python:3.9-buster as builder
FROM python:3.9-slim as builder

RUN pip install poetry==1.7.1 --no-cache-dir

ENV POETRY_NO_INTERACTION=1 \
    POETRY_INSTALLER_PARALLEL=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache \
    PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10

WORKDIR /

COPY pyproject.toml ./
RUN touch README.md

RUN poetry install --without dev --no-root && rm -rf $POETRY_CACHE_DIR

FROM python:3.9-slim as runtime

ENV VIRTUAL_ENV=/.venv \
    PATH="/.venv/bin:$PATH"

COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

COPY . .
RUN mkdir -p /tmp/prometheus-multiproc
EXPOSE 8000

CMD [ "gunicorn", "-c", "gunicorn.conf.py", "app.main:app", "--log-level", "warning" ]
