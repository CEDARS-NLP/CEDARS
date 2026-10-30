"""Project database secret resolution and provisioning support."""

import asyncio
import json

from app.common.context import ProjectContext
from app.common.database import (
    configure_project_database_url_resolver,
    global_session_factory,
)
from app.common.secrets import get_secrets_manager_client
from app.projects.models import Project


def _get_secret(secret_id: str) -> str:
    client = get_secrets_manager_client()
    response = client.get_secret_value(SecretId=secret_id)
    secret_string = response.get("SecretString")
    if not secret_string:
        raise RuntimeError("Project database secret has no SecretString")
    try:
        payload = json.loads(secret_string)
    except json.JSONDecodeError:
        return secret_string
    if not isinstance(payload, dict) or not isinstance(payload.get("database_url"), str):
        raise RuntimeError("Project database secret has an invalid payload")
    return payload["database_url"]


async def resolve_project_database_url(context: ProjectContext) -> str:
    """Resolve a ready project's stored Secrets Manager reference to its DSN."""
    async with global_session_factory() as session:
        project = await session.get(Project, context.project_id)
        if (
            not project
            or project.deleted_at is not None
            or project.database_status != "ready"
            or not project.database_secret_ref
            or project.routing_version != context.routing_version
        ):
            raise RuntimeError("Project database route is unavailable")
        secret_ref = project.database_secret_ref

    return await asyncio.to_thread(_get_secret, secret_ref)


def configure_project_database_routing() -> None:
    """Install the AWS Secrets Manager resolver for the application process."""
    configure_project_database_url_resolver(resolve_project_database_url)
