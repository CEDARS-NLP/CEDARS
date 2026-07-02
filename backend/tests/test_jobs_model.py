"""Tests for BackgroundJob model."""
import pytest

from app.jobs.models import BackgroundJob, JobStatus, JobType
from tests.conftest import seed_project_and_user


@pytest.mark.asyncio
async def test_create_background_job(app):
    """BackgroundJob can be created and persisted."""
    from app.common.database import get_session

    await seed_project_and_user(app)
    async for session in app.dependency_overrides[get_session]():
        job = BackgroundJob(
            project_id="proj-1",
            job_type=JobType.NLP,
            status=JobStatus.PENDING,
            created_by="user-1",
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        assert job.id is not None
        assert job.job_type == JobType.NLP
        assert job.status == JobStatus.PENDING
        assert job.progress == 0
        assert job.arq_job_id is None
