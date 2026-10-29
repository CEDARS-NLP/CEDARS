"""Recoverable provisioning of logical project databases on the existing cluster."""

import argparse
import asyncio
import json
from uuid import UUID

import boto3
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.models import User
from app.config import settings
from app.projects.models import Project, ProjectMember, ProjectUser


class ProvisioningError(Exception):
    """A sanitized error suitable for the project creation response."""


def project_database_name(project_id: str) -> str:
    return f"cedars_project_{UUID(project_id).hex}"


async def create_database(project_id: str) -> str:
    database_name = project_database_name(project_id)
    if not settings.project_provisioning_database_url:
        raise ProvisioningError("Project database provisioning is not configured")
    admin_url = make_url(settings.project_provisioning_database_url)
    runtime_url = make_url(settings.database_url)
    if (
        admin_url.get_backend_name() != "postgresql"
        or runtime_url.get_backend_name() != "postgresql"
    ):
        raise ProvisioningError("Project provisioning requires PostgreSQL")
    if (admin_url.host, admin_url.port or 5432) != (runtime_url.host, runtime_url.port or 5432):
        raise ProvisioningError("Provisioning and runtime databases must use the same cluster")
    if not runtime_url.username:
        raise ProvisioningError("A runtime database user is required")
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            )
            if not exists:
                owner = connection.dialect.identifier_preparer.quote_identifier(
                    runtime_url.username
                )
                await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}" OWNER {owner}')
    finally:
        await admin_engine.dispose()
    return runtime_url.set(database=database_name).render_as_string(hide_password=False)


def store_database_secret(project_id: str, database_url: str) -> str:
    client = boto3.client("secretsmanager", region_name=settings.aws_region)
    name = f"{settings.project_database_secret_prefix.rstrip('/')}/{UUID(project_id).hex}"
    payload = json.dumps({"database_url": database_url})
    try:
        response = client.create_secret(Name=name, SecretString=payload)
    except client.exceptions.ResourceExistsException:
        response = client.get_secret_value(SecretId=name)
        if json.loads(response["SecretString"]) != {"database_url": database_url}:
            raise ProvisioningError("The project database secret does not match the expected route")
    return response["ARN"]


async def seed_project_identities(
    global_session: AsyncSession, tenant_session: AsyncSession, project: Project
) -> None:
    members = (
        await global_session.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project.id)
        )
    ).all()
    for member, user in members:
        actor = await tenant_session.get(ProjectUser, user.id)
        if actor is None:
            actor = ProjectUser(
                global_user_id=user.id, project_id=project.id, email=user.email, name=user.name
            )
        actor.email = user.email
        actor.name = user.name
        actor.role = member.role.value
        actor.is_active = member.is_active and user.is_active
        actor.is_investigator = user.id == project.owner_id
        actor.membership_revision = member.membership_revision
        actor.added_by_kind = member.added_by_kind
        actor.revoked_at = member.revoked_at
        tenant_session.add(actor)
    await tenant_session.flush()
    for member, user in members:
        if member.added_by_user_id:
            added_by = await tenant_session.get(ProjectUser, member.added_by_user_id)
            if added_by is None:
                global_actor = await global_session.get(User, member.added_by_user_id)
                if global_actor is None:
                    raise ProvisioningError("Project membership actor is unavailable")
                tenant_session.add(
                    ProjectUser(
                        global_user_id=global_actor.id,
                        project_id=project.id,
                        email=global_actor.email,
                        name=global_actor.name,
                        is_active=False,
                    )
                )
                await tenant_session.flush()
            actor = await tenant_session.get(ProjectUser, user.id)
            actor.added_by_user_id = member.added_by_user_id
    await tenant_session.commit()
    for member, _user in members:
        member.synced_revision = member.membership_revision


async def _provision_steps(session: AsyncSession, project_id: str) -> None:
    from app.common.migrations import migrate_project_database

    project = await session.scalar(
        select(Project)
        .where(Project.id == project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if project is None or project.deleted_at is not None:
        raise ProvisioningError("Project is unavailable")
    if project.database_status == "ready":
        await session.commit()
        return
    database_url = await create_database(project.id)
    revision = await asyncio.to_thread(migrate_project_database, database_url)
    secret_ref = await asyncio.to_thread(store_database_secret, project.id, database_url)
    tenant_engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        factory = async_sessionmaker(tenant_engine, expire_on_commit=False)
        async with factory() as tenant_session:
            await seed_project_identities(session, tenant_session, project)
    finally:
        await tenant_engine.dispose()
    project.database_secret_ref = secret_ref
    project.database_schema_version = revision
    project.database_status = "ready"
    project.provisioning_error = None
    await session.commit()


async def provision_project(session: AsyncSession, project: Project) -> None:
    """Provision after the global project/member transaction has committed."""
    try:
        await asyncio.wait_for(
            _provision_steps(session, project.id),
            timeout=settings.project_provisioning_timeout_seconds,
        )
    except Exception as error:
        await session.rollback()
        await session.refresh(project)
        project.database_status = "failed"
        project.provisioning_error = (
            f"Project setup failed. Contact an administrator with project ID {project.id}."
        )
        await session.commit()
        raise ProvisioningError(project.provisioning_error) from error


async def retry_provisioning(project_id: str) -> None:
    from app.common.database import global_session_factory

    async with global_session_factory() as session:
        project = await session.get(Project, project_id)
        if project is None or project.deleted_at is not None:
            raise ProvisioningError("Project is unavailable")
        await provision_project(session, project)


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume setup of an existing project database")
    parser.add_argument("project_id", type=lambda value: str(UUID(value)))
    arguments = parser.parse_args()
    try:
        asyncio.run(retry_provisioning(arguments.project_id))
    except ProvisioningError as error:
        print(str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
