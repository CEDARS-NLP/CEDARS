from collections import Counter

import pytest
from sqlalchemy import text

from app.common.context import ProjectContext
from app.common.database import (
    configure_project_database_url_resolver,
    dispose_project_engines,
    get_global_engine,
    get_project_engine,
    get_project_session,
)
from app.common.model_registry import global_metadata, project_metadata


@pytest.fixture(autouse=True)
async def reset_project_engine_cache():
    await dispose_project_engines()
    configure_project_database_url_resolver(None)
    yield
    await dispose_project_engines()
    configure_project_database_url_resolver(None)


def test_project_context_is_immutable():
    context = ProjectContext(project_id="project-a")

    with pytest.raises(AttributeError):
        context.project_id = "project-b"


def test_project_context_rejects_invalid_values():
    with pytest.raises(ValueError, match="project_id"):
        ProjectContext(project_id="")
    with pytest.raises(ValueError, match="routing_version"):
        ProjectContext(project_id="project-a", routing_version=0)


@pytest.mark.asyncio
async def test_project_engines_are_cached_and_isolated(tmp_path):
    database_urls = {
        "project-a": f"sqlite+aiosqlite:///{tmp_path / 'project-a.db'}",
        "project-b": f"sqlite+aiosqlite:///{tmp_path / 'project-b.db'}",
    }
    resolver_calls: Counter[str] = Counter()

    async def resolve_database_url(context: ProjectContext) -> str:
        resolver_calls[context.project_id] += 1
        return database_urls[context.project_id]

    configure_project_database_url_resolver(resolve_database_url)
    context_a = ProjectContext(project_id="project-a")
    context_b = ProjectContext(project_id="project-b")

    engine_a = await get_project_engine(context_a)
    assert await get_project_engine(context_a) is engine_a
    engine_b = await get_project_engine(context_b)

    assert engine_a is not engine_b
    assert resolver_calls == {"project-a": 1, "project-b": 1}

    async with engine_a.begin() as connection:
        await connection.execute(text("CREATE TABLE tenant_probe (value TEXT NOT NULL)"))
        await connection.execute(text("INSERT INTO tenant_probe (value) VALUES ('only-a')"))
        result = await connection.execute(text("SELECT value FROM tenant_probe"))
        assert result.scalar_one() == "only-a"

    async with engine_b.connect() as connection:
        result = await connection.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'tenant_probe'")
        )
        assert result.first() is None


@pytest.mark.asyncio
async def test_project_engine_requires_configured_url_resolver():
    with pytest.raises(RuntimeError, match="resolver is not configured"):
        await get_project_engine(ProjectContext(project_id="project-a"))


@pytest.mark.asyncio
async def test_project_session_dependency_uses_context_database(tmp_path):
    database_urls = {
        "project-a": f"sqlite+aiosqlite:///{tmp_path / 'project-a.db'}",
        "project-b": f"sqlite+aiosqlite:///{tmp_path / 'project-b.db'}",
    }

    async def resolve_database_url(context: ProjectContext) -> str:
        return database_urls[context.project_id]

    configure_project_database_url_resolver(resolve_database_url)
    contexts = [ProjectContext(project_id="project-a"), ProjectContext(project_id="project-b")]

    for context in contexts:
        dependency = get_project_session(lambda: context)
        async for session in dependency(context=context):
            await session.execute(text("CREATE TABLE tenant_probe (value TEXT NOT NULL)"))
            await session.execute(
                text("INSERT INTO tenant_probe (value) VALUES (:project_id)"),
                {"project_id": context.project_id},
            )
            result = await session.execute(text("SELECT value FROM tenant_probe"))
            assert result.scalar_one() == context.project_id
            await session.commit()

    project_a_engine = await get_project_engine(contexts[0])
    project_b_engine = await get_project_engine(contexts[1])
    assert project_a_engine is not project_b_engine

    async with project_a_engine.connect() as connection:
        result = await connection.execute(text("SELECT value FROM tenant_probe"))
        assert result.scalar_one() == "project-a"


def test_global_engine_accessor_returns_shared_engine():
    assert get_global_engine() is get_global_engine()


def test_model_metadata_is_split_without_cross_database_foreign_keys():
    assert set(global_metadata.tables) == {"users", "projects", "project_members"}
    assert "ProjectUsers" in project_metadata.tables
    assert "patients" in project_metadata.tables
    assert "notes" in project_metadata.tables
    assert "Annotations" in project_metadata.tables
    assert "evaluation_sessions_v2" in project_metadata.tables
    assert "RESULTS" in project_metadata.tables

    cross_database_foreign_keys = [
        (table.name, element.target_fullname)
        for table in project_metadata.tables.values()
        for constraint in table.foreign_key_constraints
        for element in constraint.elements
        if element.target_fullname.startswith(("users.", "projects."))
    ]
    assert cross_database_foreign_keys == []
