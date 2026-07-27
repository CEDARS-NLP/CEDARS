import os
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.annotations.models import Annotation, AnnotationToken  # noqa: F401
from app.audit.models import AuditEntry  # noqa: F401
from app.auth.models import User  # noqa: F401 — ensure table is registered in metadata
from app.common.database import get_session
from app.connectors.models import DataSource, Note, NoteTag, Patient  # noqa: F401
from app.evaluation.models import (  # noqa: F401
    EvaluationSession,
    PatientResult,
    SearchMatch,
)
from app.jobs.models import BackgroundJob  # noqa: F401
from app.main import create_app
from app.nlp.models import NlpJob, NotePrediction, SearchQuery, Sentence  # noqa: F401
from app.pipeline.models import (  # noqa: F401 — register pipeline tables in metadata
    EventConfig,
    Evidence,
    PatientTask,
    PipelineRun,
)
from app.predictors.models import PredictorConfig  # noqa: F401
from app.projects.models import Project, ProjectMember  # noqa: F401
from app.workflow.models import PatientReviewResult, ReviewSession  # noqa: F401

TEST_DATABASE_URL = "sqlite+aiosqlite://"

# When CEDARS_TEST_POSTGRES=1, the whole suite runs against a throwaway Postgres
# container built from Alembic migrations (not create_all). This catches the
# class of bugs SQLite hides: enum name-vs-value casing, int/str comparisons,
# strict FK enforcement, and create_all-vs-migration drift.
_USE_POSTGRES = os.getenv("CEDARS_TEST_POSTGRES") == "1"


@pytest.fixture(scope="session")
def _postgres_url():
    """Session-scoped Postgres URL; yields an asyncpg URL. Skips if disabled.

    Two sources:
      - CEDARS_TEST_POSTGRES_URL set (CI with a Postgres service container) → use it.
      - otherwise spin up a throwaway container via testcontainers (local dev;
        needs Docker — on macOS set DOCKER_HOST to your Docker Desktop socket).
    """
    if not _USE_POSTGRES:
        yield None
        return

    explicit = os.getenv("CEDARS_TEST_POSTGRES_URL")
    if explicit:
        yield explicit
        return

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        # testcontainers returns a psycopg2 URL; normalize to asyncpg for the app.
        sync_url = pg.get_connection_url()  # postgresql+psycopg2://...
        async_url = sync_url.replace("+psycopg2", "+asyncpg")
        yield async_url


def _run_migrations(async_url: str) -> None:
    """Run Alembic migrations against the target DB (sync engine under the hood)."""
    from alembic import command
    from alembic.config import Config

    # Alembic env reads settings.database_url; point it at the test DB.
    os.environ["CEDARS_DATABASE_URL"] = async_url
    from app.config import settings

    settings.database_url = async_url  # in case settings was already instantiated

    cfg = Config(str(__import__("pathlib").Path(__file__).parent.parent / "alembic.ini"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def _force_sync_nlp_dispatch():
    """Force dispatch_nlp_job to use the synchronous fallback path in all tests.

    When Redis is running locally, ARQ enqueue succeeds but no worker
    processes the job, leaving it stuck in 'pending'. Patching create_pool
    to raise ensures the sync fallback is always used in tests.
    """
    with patch("arq.create_pool", side_effect=ConnectionError("no Redis in tests")):
        yield


@pytest.fixture
async def app(_postgres_url):
    if _USE_POSTGRES:
        # Build schema from Alembic migrations (matches production), then create
        # a per-test schema by truncating between tests via drop/create all.
        _run_migrations(_postgres_url)
        engine = create_async_engine(_postgres_url, echo=False)
    else:
        engine = create_async_engine(
            TEST_DATABASE_URL,
            echo=False,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    test_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    application = create_app()

    async def override_get_session():
        async with test_session() as session:
            yield session

    application.dependency_overrides[get_session] = override_get_session
    yield application

    if _USE_POSTGRES:
        # Nuke and recreate the public schema — drops all tables, enum types, and
        # the alembic_version marker in one shot, avoiding FK-dependency ordering
        # issues. Next test's migration run starts from a clean schema.
        # First terminate any lingering backends (e.g. an ARQ-dispatch path that
        # left a connection open) so DROP SCHEMA can't deadlock against them.
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
            await conn.exec_driver_sql("DROP SCHEMA public CASCADE")
            await conn.exec_driver_sql("CREATE SCHEMA public")
    else:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
def client_factory(app):
    """Factory to create new AsyncClient instances (useful for multi-user tests).

    Usage:
        async with client_factory() as c:
            await register_and_login(c, "user@test.com")
            ...
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _make_client():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac

    return _make_client


async def seed_project_and_user(app, *, project_id="proj-1", user_id="user-1"):
    """Insert a User and Project (+ membership) with the given IDs.

    Model-level unit tests historically used bare placeholder IDs like "proj-1";
    Postgres enforces the FKs those rows depend on (SQLite did not), so tests
    must seed real parent rows first. Returns (project_id, user_id).
    """
    from app.common.database import get_session
    from app.projects.models import ProjectRole

    async for session in app.dependency_overrides[get_session]():
        session.add(
            User(id=user_id, email=f"{user_id}@test.com", name="Test", password_hash="x")
        )
        session.add(Project(id=project_id, name="Test Project", owner_id=user_id))
        await session.flush()
        session.add(
            ProjectMember(project_id=project_id, user_id=user_id, role=ProjectRole.ADMIN)
        )
        await session.commit()
        break
    return project_id, user_id


@pytest.fixture
async def auth_client(app):
    """Client pre-authenticated with a test user via cookies."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        # Register a test user
        await ac.post(
            "/api/v1/auth/register",
            json={"email": "test@example.com", "name": "Test User", "password": "testpass123"},
        )
        # Login — server sets cookies on response
        resp = await ac.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "testpass123"},
        )
        # httpx AsyncClient automatically stores cookies from Set-Cookie headers
        # and sends them on subsequent requests
        assert resp.status_code == 200
        yield ac
