from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.projects.models import Project, ProjectMember, ProjectUser
from app.projects.provisioning import ProvisioningError, project_database_name, provision_project
from tests.conftest import seed_project_and_user


def test_database_name_rejects_sql_identifiers():
    with pytest.raises(ValueError):
        project_database_name('"; DROP DATABASE postgres; --')
    identity = uuid4()
    assert project_database_name(str(identity)) == f"cedars_project_{identity.hex}"


async def test_failure_retains_global_rows_and_redacts_error(app, monkeypatch):
    project_id, user_id = await seed_project_and_user(app)
    monkeypatch.setattr(
        "app.projects.provisioning.create_database",
        AsyncMock(side_effect=RuntimeError("postgresql://admin:secret@private-host/db")),
    )
    async with app.state.test_session_factory() as session:
        project = await session.get(Project, project_id)
        with pytest.raises(ProvisioningError, match="Contact an administrator"):
            await provision_project(session, project)
        assert project.database_status == "failed"
        assert "secret@" not in project.provisioning_error
        member = await session.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
            )
        )
        assert member is not None


async def test_ready_project_does_not_repeat_provisioning(app, monkeypatch):
    project_id, _ = await seed_project_and_user(app)
    create = AsyncMock()
    monkeypatch.setattr("app.projects.provisioning.create_database", create)
    async with app.state.test_session_factory() as session:
        project = await session.get(Project, project_id)
        project.database_status = "ready"
        await session.commit()
        await provision_project(session, project)
    create.assert_not_awaited()


async def test_provisioning_seeds_separate_tenant_and_marks_ready(app, tmp_path, monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    project_id, user_id = await seed_project_and_user(app)
    tenant_url = f"sqlite+aiosqlite:///{tmp_path / 'provisioned-tenant.db'}"

    def tenant_engine_with_foreign_keys(*arguments, **keywords):
        tenant_engine = create_async_engine(*arguments, **keywords)

        @event.listens_for(tenant_engine.sync_engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        return tenant_engine

    monkeypatch.setattr(
        "app.projects.provisioning.create_async_engine", tenant_engine_with_foreign_keys
    )
    monkeypatch.setattr(
        "app.projects.provisioning.create_database", AsyncMock(return_value=tenant_url)
    )
    store = Mock(return_value="user-cedars/project-test")
    monkeypatch.setattr("app.projects.provisioning.store_database_secret", store)
    async with app.state.test_session_factory() as session:
        project = await session.get(Project, project_id)
        member = await session.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
            )
        )
        member.added_by_kind = "user"
        member.added_by_user_id = user_id
        await session.commit()
        await provision_project(session, project)
        assert project.database_status == "ready"
        assert project.database_schema_version == "p0001_project_baseline"
        assert project.database_secret_ref == "user-cedars/project-test"
        assert project.provisioning_error is None
        member = await session.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
            )
        )
        assert member.synced_revision == member.membership_revision
    engine = create_async_engine(tenant_url)
    try:
        async with async_sessionmaker(engine)() as session:
            actor = await session.get(ProjectUser, user_id)
            assert actor.is_active
            assert actor.is_investigator
            assert actor.role == "admin"
            assert actor.added_by_user_id == user_id
    finally:
        await engine.dispose()
    store.assert_called_once_with(project_id, tenant_url)


async def test_provisioning_timeout_records_retryable_failure(app, monkeypatch):
    import asyncio

    project_id, _ = await seed_project_and_user(app)
    monkeypatch.setattr(
        "app.projects.provisioning.settings.project_provisioning_timeout_seconds", 1
    )

    async def blocked_database(_project_id):
        await asyncio.Event().wait()

    monkeypatch.setattr("app.projects.provisioning.create_database", blocked_database)
    async with app.state.test_session_factory() as session:
        project = await session.get(Project, project_id)
        with pytest.raises(ProvisioningError, match=project_id):
            await provision_project(session, project)
        assert project.database_status == "failed"
        assert project.database_schema_version is None


async def test_creation_failure_returns_sanitized_message_and_keeps_membership(
    app, auth_client, monkeypatch
):
    monkeypatch.setattr("app.projects.service.provision_project", provision_project)
    monkeypatch.setattr(
        "app.projects.provisioning.create_database",
        AsyncMock(side_effect=RuntimeError("postgresql://admin:private-password@private-host/db")),
    )
    response = await auth_client.post("/api/v1/projects", json={"name": "Failed setup"})
    assert response.status_code == 503
    assert "Contact an administrator" in response.json()["detail"]
    assert "private-password" not in response.text
    projects = (await auth_client.get("/api/v1/projects")).json()
    assert len(projects) == 1
    assert projects[0]["database_status"] == "failed"
    assert projects[0]["id"] in response.json()["detail"]


@pytest.mark.parametrize("stage", ["migration", "secret", "seed"])
async def test_external_failure_never_marks_ready(app, monkeypatch, stage):
    project_id, _ = await seed_project_and_user(app)
    monkeypatch.setattr(
        "app.projects.provisioning.create_database", AsyncMock(return_value="sqlite+aiosqlite://")
    )
    migrate = Mock(return_value="tenant-head")
    store = Mock(return_value="secret-ref")
    seed = AsyncMock()
    {"migration": migrate, "secret": store, "seed": seed}[stage].side_effect = RuntimeError(
        "secret"
    )
    monkeypatch.setattr("app.common.migrations.migrate_project_database", migrate)
    monkeypatch.setattr("app.projects.provisioning.store_database_secret", store)
    monkeypatch.setattr("app.projects.provisioning.seed_project_identities", seed)
    async with app.state.test_session_factory() as session:
        project = await session.get(Project, project_id)
        with pytest.raises(ProvisioningError):
            await provision_project(session, project)
        assert project.database_status == "failed"
        assert project.database_schema_version is None
