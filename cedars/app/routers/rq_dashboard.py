"""Auth-gated bridge to the per-project stock rq-dashboard.

Every request is required to satisfy ``require_project_admin`` *before* it is
forwarded into the cached, project-scoped Flask/rq-dashboard ASGI app built by
:mod:`app.rq_dashboard_gateway`. rq-dashboard itself has no auth of its own, so
this route is the only access-control boundary for it.
"""
from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from ..dependencies import ProjectContext, require_project_admin
from ..rq_dashboard_gateway import get_dashboard_asgi_app

router = APIRouter(prefix="/projects/{project_id}/rq", tags=["rq-dashboard"])


def _make_receive(body: bytes):
    """A one-shot ASGI ``receive`` callable that replays an already-read body."""
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


async def _call_asgi_app(asgi_app, scope, receive):
    """Invoke an ASGI app and capture its response instead of streaming it."""
    status_code = 500
    raw_headers = []
    body_chunks = []

    async def send(message):
        nonlocal status_code, raw_headers
        if message["type"] == "http.response.start":
            status_code = message["status"]
            raw_headers = message.get("headers", [])
        elif message["type"] == "http.response.body":
            body_chunks.append(message.get("body", b""))

    await asgi_app(scope, receive, send)
    return status_code, raw_headers, b"".join(body_chunks)


@router.api_route("/{path:path}", methods=["GET", "POST", "HEAD"])
async def rq_dashboard_proxy(path: str, request: Request,  # noqa: ARG001 - path drives routing only
                            ctx: ProjectContext = Depends(require_project_admin)):
    """Serve the stock rq-dashboard UI for this project (admin-gated)."""
    asgi_app = get_dashboard_asgi_app(ctx.project_id)
    body = await request.body()
    status_code, raw_headers, content = await _call_asgi_app(
        asgi_app, request.scope, _make_receive(body))
    headers = {name.decode("latin-1"): value.decode("latin-1") for name, value in raw_headers}
    return Response(content=content, status_code=status_code, headers=headers)
