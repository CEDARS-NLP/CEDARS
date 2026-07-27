"""End-to-end DB-level test of the v1 workflow: NLP -> adjudicate.

Uses the in-memory SQLite ``app`` fixture and a direct session (matching the
conftest seeding pattern) to exercise the ported processor + service against a
wildcard query (which matches on the blank spaCy model without a lemmatizer).
"""

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.common.database import get_session


async def test_nlp_and_review_flow(app):
    from app.annotations.models import Annotation, AnnotationToken
    from app.connectors.models import Note, Patient, PatientStatus
    from app.nlp import processor
    from app.projects.models import Project, ProjectMember, ProjectRole
    from app.auth.models import User
    from app.workflow import db_ops, service

    async for session in app.dependency_overrides[get_session]():
        # --- Seed project, user, patient, note ---
        session.add(User(id="u1", email="u1@test.com", name="Tester", password_hash="x"))
        session.add(Project(id="p1", name="Proj", owner_id="u1"))
        await session.flush()
        session.add(ProjectMember(project_id="p1", user_id="u1", role=ProjectRole.ADMIN))
        session.add(
            Patient(id="pat1", project_id="p1", patient_id_ext="P001", status=PatientStatus.NEW)
        )
        session.add(
            Note(
                id="note1",
                project_id="p1",
                patient_id="pat1",
                text_id="N001",
                note_date=datetime(2026, 1, 1, tzinfo=UTC),
                text="Patient has a clot in the leg. Otherwise well.",
            )
        )
        await db_ops.save_query(
            session,
            "p1",
            "clot*",
            use_negation=False,
            hide_duplicates=True,
            skip_after_event=False,
            nlp_apply=False,
            created_by="u1",
        )
        await session.commit()

        # --- Run the ported NLP processor ---
        await processor.process_patient_notes(session, "p1", "pat1")

        ann_count = (
            await session.execute(
                select(func.count(Annotation.id)).where(Annotation.project_id == "p1")
            )
        ).scalar_one()
        assert ann_count >= 1
        tok_count = (
            await session.execute(select(func.count(AnnotationToken.id)))
        ).scalar_one()
        assert tok_count >= 1

        # --- Adjudication flow ---
        pid, _status, annotation = await service.get_next_patient(
            session, "p1", "u1", "Tester"
        )
        assert pid == "pat1"
        assert annotation is not None
        assert "clot" in annotation.highlighted_sentence.lower()

        complete, _ = await service.apply_action(
            session, "p1", "pat1", "u1", "Tester", "adjudicate", "", None
        )
        assert complete is True

        patient = await session.get(Patient, "pat1")
        assert patient.status == PatientStatus.REVIEWED
        break
