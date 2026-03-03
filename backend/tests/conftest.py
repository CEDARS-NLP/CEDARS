import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.auth.models import User  # noqa: F401 — ensure table is registered in metadata
from app.projects.models import Project, ProjectMember  # noqa: F401
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
