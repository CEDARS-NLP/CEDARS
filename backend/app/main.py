"""FastAPI application factory for CEDARS v2."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.connectors.router import router as data_router
from app.annotations.router import router as annotations_router
from app.evaluation.router import router as evaluation_router
from app.export.router import router as export_router
from app.nlp.router import router as nlp_router
from app.admin.router import router as admin_router
from app.audit.router import router as audit_router
from app.predictors.router import router as predictors_router
from app.projects.router import router as projects_router


def _ensure_s3_bucket():
    """Create the S3 bucket if it doesn't exist (for local MinIO dev)."""
    from app.config import settings

    if not settings.s3_bucket or not settings.s3_endpoint:
        return
    try:
        from app.common.s3 import get_s3_client

        client = get_s3_client()
        try:
            client.head_bucket(Bucket=settings.s3_bucket)
        except client.exceptions.ClientError:
            client.create_bucket(Bucket=settings.s3_bucket)
    except Exception:
        # Non-fatal — S3 may not be running in all environments
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup/shutdown events."""
    # Startup
    _ensure_s3_bucket()
    yield
    # Shutdown


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title="CEDARS",
        description="Clinical Event Detection and Recording System v2",
        version="2.0.0",
        lifespan=lifespan,
    )

    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(application).expose(application)

    from app.config import settings

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(auth_router)
    application.include_router(projects_router)
    application.include_router(data_router)
    application.include_router(predictors_router)
    application.include_router(nlp_router)
    application.include_router(annotations_router)
    application.include_router(evaluation_router)
    application.include_router(export_router)
    application.include_router(admin_router)
    application.include_router(audit_router)

    @application.get("/api/v1/health")
    async def health_check():
        return {"status": "ok", "version": "2.0.0"}

    return application


app = create_app()
