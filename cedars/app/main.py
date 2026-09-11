"""FastAPI application factory for CEDARS.

Serves the REST API under ``/api/v1`` (consumed by the React SPA). Routers are
added incrementally as each workflow phase is ported.
"""
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import setup_logging
from .routers import (adjudicate, auth, data, download, internal, projects,
                      query, rq_dashboard, stats)
from .settings import settings


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    setup_logging()

    app = FastAPI(
        title="CEDARS API",
        version="2025.1",
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix="/api/v1")

    @api.get("/health", tags=["health"])
    def health():
        return {"status": "ok"}

    api.include_router(auth.router)
    api.include_router(projects.router)
    api.include_router(data.router)
    api.include_router(query.router)
    api.include_router(adjudicate.router)
    api.include_router(stats.router)
    api.include_router(download.router)
    api.include_router(internal.router)
    api.include_router(rq_dashboard.router)

    app.include_router(api)

    # Optional Prometheus metrics at /metrics (no-op if the package is absent).
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator().instrument(app).expose(
            app, endpoint="/metrics", include_in_schema=False
        )
    except (ImportError, ValueError):
        print("Prometheus metrics not enabled (missing package or required folder).")

    return app


app = create_app()
