"""Cross-backend enum round-trip guard.

Every persisted enum must insert AND read back identically on both backends:
SQLite (schema via ``create_all``) and Postgres (schema via Alembic migrations,
enabled with ``CEDARS_TEST_POSTGRES=1``).

This is the durable guard against the enum name-vs-value casing bug class that
crashed production but passed the SQLite-only suite (see the remediation plan,
docs/plans/2026-07-02-backend-code-review-remediation.md, Phase 2). SQLite is
lax about enum labels; Postgres enforces the native enum type, so a member whose
bound representation is absent from the PG type raises on INSERT. Exercising
*every member of every persisted enum* here means such a divergence can never
again be structurally invisible until deploy.

Coverage note: three enums are stored as VARCHAR rather than native PG enum
types (Annotation.review_status, EvaluationSession.status, PatientResult.status)
to sidestep the legacy PG enum types that linger from v1. They are included here
too — a (str, Enum) member persisted to a String column round-trips to its
value, and equality with the member still holds.
"""

import pytest

from app.annotations.models import Annotation, ReviewStatus
from app.audit.models import AuditAction, AuditEntry
from app.auth.models import User, UserRole
from app.common.database import get_session
from app.common.utils import now_utc
from app.connectors.models import (
    ConnectorType,
    DataSource,
    IngestionStatus,
    Note,
    Patient,
    PatientStatus,
)
from app.evaluation.models import (
    EvaluationSession,
    PatientResult,
    PatientResultStatus,
    SessionStatus,
)
from app.jobs.models import BackgroundJob, JobStatus, JobType
from app.nlp.models import NlpJob, NlpJobStatus
from app.pipeline.models import (
    EventConfig,
    PatientTask,
    PatientTaskStatus,
    PipelineRun,
    PipelineRunStatus,
)
from app.predictors.models import PredictorConfig, PredictorType
from app.projects.models import ProjectMember, ProjectRole
from tests.conftest import seed_project_and_user

pytestmark = pytest.mark.asyncio


async def _seed_parents(session, pid, uid):
    """Create the FK parents the enum-bearing rows depend on. Returns ids."""
    patient = Patient(project_id=pid, patient_id_ext="ext-parent", status=PatientStatus.NEW)
    session.add(patient)
    await session.flush()

    note = Note(
        project_id=pid,
        patient_id=patient.id,
        text_id="note-parent",
        note_date=now_utc(),
        text="parent note text",
    )
    session.add(note)

    ec = EventConfig(
        project_id=pid,
        name="MI",
        description="MI",
        include_criteria="x",
        exclude_criteria="y",
        search_patterns={},
        llm_provider="ollama",
        llm_model="llama3",
    )
    session.add(ec)
    await session.flush()

    run = PipelineRun(
        project_id=pid,
        event_config_id=ec.id,
        run_type="sample",
        status=PipelineRunStatus.QUEUED,
        config_snapshot={},
        total_patients=0,
        created_by=uid,
    )
    session.add(run)

    sess = EvaluationSession(project_id=pid, created_by=uid, status=SessionStatus.DRAFT)
    session.add(sess)

    await session.commit()
    return {
        "patient_id": patient.id,
        "note_id": note.id,
        "event_config_id": ec.id,
        "run_id": run.id,
        "session_id": sess.id,
    }


def _build_specs(pid, uid, parents):
    """Return [(enum_cls, attr, build(member) -> [orm_objs])].

    build returns a list of rows to persist; the enum-bearing row is last.
    Every member of every persisted enum is exercised.
    """
    return [
        (ConnectorType, "connector_type",
         lambda m: [DataSource(project_id=pid, name=f"ds-{m.name}", connector_type=m)]),
        (IngestionStatus, "status",
         lambda m: [DataSource(project_id=pid, name=f"ds-st-{m.name}",
                               connector_type=ConnectorType.FILE_UPLOAD, status=m)]),
        (PatientStatus, "status",
         lambda m: [Patient(project_id=pid, patient_id_ext=f"ext-{m.name}", status=m)]),
        (UserRole, "role",
         lambda m: [User(email=f"role-{m.name}@t.com", name="x", password_hash="x", role=m)]),
        (PredictorType, "predictor_type",
         lambda m: [PredictorConfig(project_id=pid, predictor_type=m,
                                    name=f"pc-{m.name}", created_by=uid)]),
        (AuditAction, "action",
         lambda m: [AuditEntry(project_id=pid, action=m)]),
        (NlpJobStatus, "status",
         lambda m: [NlpJob(project_id=pid, status=m)]),
        (JobType, "job_type",
         lambda m: [BackgroundJob(job_type=m)]),
        (JobStatus, "status",
         lambda m: [BackgroundJob(job_type=JobType.NLP, status=m)]),
        (PipelineRunStatus, "status",
         lambda m: [PipelineRun(project_id=pid, event_config_id=parents["event_config_id"],
                                run_type="sample", status=m, config_snapshot={},
                                created_by=uid)]),
        (PatientTaskStatus, "status",
         lambda m: [PatientTask(pipeline_run_id=parents["run_id"],
                                patient_id=parents["patient_id"], status=m)]),
        (ProjectRole, "role",
         lambda m: _project_member_rows(pid, m)),
        (ReviewStatus, "review_status",
         lambda m: [Annotation(project_id=pid, patient_id=parents["patient_id"],
                               note_id=parents["note_id"], sentence_text="x",
                               review_status=m)]),
        (SessionStatus, "status",
         lambda m: [EvaluationSession(project_id=pid, created_by=uid, status=m)]),
        (PatientResultStatus, "status",
         lambda m: [PatientResult(session_id=parents["session_id"],
                                  patient_id=parents["patient_id"], status=m)]),
    ]


def _project_member_rows(pid, member):
    """ProjectMember needs a distinct user per row (unique project_id+user_id)."""
    u = User(email=f"pm-{member.name}@t.com", name="x", password_hash="x")
    return [u, ProjectMember(project_id=pid, user_id=u.id, role=member)]


async def test_all_enums_roundtrip_identically(app):
    """Every member of every persisted enum inserts and reads back as itself.

    On Postgres a member bound to a representation absent from the native enum
    type raises on commit; that surfaces here as a failure entry rather than a
    silent SQLite pass.
    """
    pid, uid = await seed_project_and_user(app)

    async for session in app.dependency_overrides[get_session]():
        parents = await _seed_parents(session, pid, uid)
        specs = _build_specs(pid, uid, parents)

        failures: list[str] = []
        for enum_cls, attr, build in specs:
            for member in enum_cls:
                rows = build(member)
                target = rows[-1]
                try:
                    session.add_all(rows)
                    await session.commit()
                except Exception as exc:  # noqa: BLE001 — report, don't abort the sweep
                    await session.rollback()
                    failures.append(
                        f"{enum_cls.__name__}.{member.name} ({member.value!r}): "
                        f"INSERT failed: {type(exc).__name__}: {exc}"
                    )
                    continue

                await session.refresh(target)
                actual = getattr(target, attr)
                if actual != member:
                    failures.append(
                        f"{enum_cls.__name__}.{member.name}: read back {actual!r}, "
                        f"expected {member!r}"
                    )
                # (str, Enum) members equal their value; the stored form must too.
                if actual != member.value:
                    failures.append(
                        f"{enum_cls.__name__}.{member.name}: read back {actual!r} "
                        f"!= value {member.value!r}"
                    )

        assert not failures, "Enum round-trip failures:\n" + "\n".join(failures)
        break


async def test_patient_task_no_match_roundtrips(app):
    """Regression guard: PatientTaskStatus.NO_MATCH round-trips on both backends.

    NO_MATCH is the member whose PG enum label was added by a later ALTER
    (ec642691720e). The model binds the lowercase value via ``enum_column``; this
    asserts that binding matches the native type so a task reaching NO_MATCH
    persists rather than crashing on Aurora.
    """
    pid, uid = await seed_project_and_user(app)

    async for session in app.dependency_overrides[get_session]():
        parents = await _seed_parents(session, pid, uid)
        task = PatientTask(
            pipeline_run_id=parents["run_id"],
            patient_id=parents["patient_id"],
            status=PatientTaskStatus.NO_MATCH,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        assert task.status == PatientTaskStatus.NO_MATCH
        assert task.status == "no_match"
        break


async def test_job_status_cancelled_roundtrips(app):
    """Regression guard: JobStatus.CANCELLED round-trips on both backends.

    CANCELLED was added to the ``jobstatus`` PG type by a later ALTER
    (b5f066242811). BackgroundJob binds the enum NAME (native uppercase type),
    so this confirms the ALTER used the matching representation.
    """
    async for session in app.dependency_overrides[get_session]():
        job = BackgroundJob(job_type=JobType.NLP, status=JobStatus.CANCELLED)
        session.add(job)
        await session.commit()
        await session.refresh(job)
        assert job.status == JobStatus.CANCELLED
        assert job.status == "cancelled"
        break
