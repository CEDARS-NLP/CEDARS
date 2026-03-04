import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.auth.models import User  # noqa: F401 — ensure table is registered in metadata
from app.projects.models import Project, ProjectMember  # noqa: F401
from app.connectors.models import DataSource, Patient, Note  # noqa: F401
from app.predictors.models import PredictorConfig  # noqa: F401
from app.nlp.models import Sentence, SearchQuery, NlpJob  # noqa: F401
from app.annotations.models import Annotation  # noqa: F401
from app.evaluation.models import EvaluationSession, EvaluationJudgment, ValidatedPredictor  # noqa: F401
from app.jobs.models import BackgroundJob  # noqa: F401
from app.common.database import get_session
from app.main import create_app

TEST_DATABASE_URL = "sqlite+aiosqlite:///test.db"


@pytest.fixture
async def app():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    test_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    application = create_app()

    async def override_get_session():
        async with test_session() as session:
            yield session

    application.dependency_overrides[get_session] = override_get_session
    yield application

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
