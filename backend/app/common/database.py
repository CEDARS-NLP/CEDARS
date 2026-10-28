"""Async SQLAlchemy database engine and session factory."""

import asyncio
from collections import OrderedDict
from collections.abc import AsyncGenerator, Awaitable, Callable

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.common.context import ProjectContext
from app.common.model_registry import create_all_metadata
from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
global_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

ProjectDatabaseUrlResolver = Callable[[ProjectContext], Awaitable[str]]
ProjectContextDependency = Callable[..., ProjectContext | Awaitable[ProjectContext]]

_project_database_url_resolver: ProjectDatabaseUrlResolver | None = None
_project_engines: OrderedDict[tuple[str, int], AsyncEngine] = OrderedDict()
_project_engine_lock = asyncio.Lock()


def get_global_engine() -> AsyncEngine:
    """Return the process-wide engine for users, projects, and memberships."""
    return engine


def configure_project_database_url_resolver(
    resolver: ProjectDatabaseUrlResolver | None,
) -> None:
    """Install the deployment's secret-provider-backed project URL resolver."""
    global _project_database_url_resolver
    if _project_engines:
        raise RuntimeError("Cannot replace the project URL resolver while engines are cached")
    _project_database_url_resolver = resolver


async def get_project_engine(context: ProjectContext) -> AsyncEngine:
    """Resolve a trusted project context to its cached, process-local engine.

    The resolver must fetch connection details from the configured external secret
    provider. Credentials are never accepted from a request or stored in this cache's key.
    """
    resolver = _project_database_url_resolver
    if resolver is None:
        raise RuntimeError("Project database URL resolver is not configured")

    key = (context.project_id, context.routing_version)
    cached = _project_engines.get(key)
    if cached is not None:
        _project_engines.move_to_end(key)
        return cached

    async with _project_engine_lock:
        cached = _project_engines.get(key)
        if cached is not None:
            _project_engines.move_to_end(key)
            return cached

        database_url = await resolver(context)
        project_engine = create_async_engine(
            database_url,
            echo=False,
            pool_size=settings.project_db_pool_size,
            max_overflow=settings.project_db_max_overflow,
            pool_pre_ping=True,
        )
        _project_engines[key] = project_engine
        evicted: list[AsyncEngine] = []
        while len(_project_engines) > settings.project_engine_cache_size:
            _, old_engine = _project_engines.popitem(last=False)
            evicted.append(old_engine)
        for old_engine in evicted:
            await old_engine.dispose()
        return project_engine


async def dispose_project_engines() -> None:
    """Dispose cached project pools, for orderly application and worker shutdown."""
    engines = list(_project_engines.values())
    _project_engines.clear()
    for project_engine in engines:
        await project_engine.dispose()


def get_project_session(
    context_dependency: ProjectContextDependency,
) -> Callable[..., AsyncGenerator[AsyncSession, None]]:
    """Build a FastAPI dependency that opens a session for a trusted project context."""

    async def dependency(
        context: ProjectContext = Depends(context_dependency),
    ) -> AsyncGenerator[AsyncSession, None]:
        project_engine = await get_project_engine(context)
        project_session_factory = async_sessionmaker(
            project_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with project_session_factory() as session:
            yield session

    return dependency


async def get_project_session_factory(
    context: ProjectContext,
) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound only to the selected project's database."""
    project_engine = await get_project_engine(context)
    return async_sessionmaker(project_engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create both table sets together for local tooling and tests only."""
    async with engine.begin() as conn:
        await conn.run_sync(create_all_metadata)


async def get_global_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a session for global identity/project tables."""
    async with global_session_factory() as session:
        yield session
