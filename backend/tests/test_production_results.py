from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from app.annotations.models import Annotation
from app.auth.models import User
from app.connectors.models import Note, Patient
from app.export.service import export_annotations, export_results, format_results_csv
from app.production.models import NotePrediction, ProductionRun, ProductionState
from app.production.results import refresh_patient_result, refresh_project_results
from app.projects.models import Project, ProjectMember, ProjectRole, ProjectUser


@pytest.mark.asyncio
async def test_refresh_and_export_production_results(session_factory):
    async with session_factory() as db:
        user = User(email="results@example.test", name="Reviewer", password_hash="unused")
        db.add(user)
        await db.flush()
        project = Project(name="Results", owner_id=user.id)
        db.add(project)
        await db.flush()
        db.add(
            ProjectUser(
                global_user_id=user.id,
                project_id=project.id,
                email=user.email,
                name=user.name,
                role=ProjectRole.ADMIN,
                is_investigator=True,
            )
        )
        db.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.ADMIN))

        patient = Patient(
            project_id=project.id,
            patient_id_ext="external-patient-1",
            reviewed_by=user.id,
            reviewed_at=datetime(2025, 1, 4, 9),
        )
        db.add(patient)
        await db.flush()
        note = Note(
            project_id=project.id,
            patient_id=patient.id,
            patient_id_ext=patient.patient_id_ext,
            text_id="external-note-1",
            note_date=datetime(2025, 1, 3, 12),
            text="The event was confirmed.",
        )
        run = ProductionRun(project_id=project.id, status="completed")
        db.add_all([note, run])
        await db.flush()
        db.add(ProductionState(project_id=project.id, active_run_id=run.id))

        prediction = NotePrediction(
            project_id=project.id,
            run_id=run.id,
            text_id=note.text_id,
            patient_id=patient.patient_id_ext,
            note_uuid=note.id,
            patient_uuid=patient.id,
            status="succeeded",
            label=1,
            score=0.97,
            reasoning="Confirmed in the note.",
            model_fingerprint="test-model",
        )
        current_annotation = Annotation(
            project_id=project.id,
            text_id=note.text_id,
            patient_id=patient.patient_id_ext,
            patient_uuid=patient.id,
            note_uuid=note.id,
            text_date=date(2025, 1, 3),
            sentence="The event was confirmed.",
            token="event",
            isNegated=False,
            note_start_index=4,
            note_end_index=9,
            sentence_number=0,
            sentence_start=0,
            sentence_end=26,
            status="R",
            review_reason="human_event",
            reviewed_by=user.id,
            reviewer_notes="Confirmed by review.",
        )
        historical_annotation = Annotation(
            project_id=project.id,
            text_id=note.text_id,
            patient_id=patient.patient_id_ext,
            patient_uuid=patient.id,
            note_uuid=note.id,
            text_date=date(2025, 1, 3),
            sentence="A second matching sentence.",
            token="matching",
            isNegated=False,
            note_start_index=1,
            note_end_index=9,
            sentence_number=1,
            sentence_start=27,
            sentence_end=55,
            status="U",
        )
        db.add_all([prediction, current_annotation, historical_annotation])
        await db.flush()
        patient.event_date = date(2025, 1, 3)
        patient.event_reviewer = user.id
        patient.event_annotation_id = current_annotation.annotation_id
        await db.flush()

        result = await refresh_patient_result(db, project.id, patient.id)
        await db.flush()

        assert result is not None
        assert result.patient_id == "external-patient-1"
        assert result.processing_status == "completed"
        assert result.review_status == "reviewed"
        assert result.total_notes == 1
        assert result.total_sentences == 2
        assert result.reviewed_sentences == 1
        assert result.max_score == 0.97
        assert result.max_score_note_id == "external-note-1"
        assert result.event_date == date(2025, 1, 3)
        assert result.event_annotation_id == current_annotation.annotation_id
        assert result.comments == "Confirmed by review."

        annotations = await export_annotations(db, project.id)
        assert [row["event_date"] for row in annotations] == [date(2025, 1, 3), None]
        assert annotations[0]["patient_id"] == "external-patient-1"
        assert annotations[0]["predicted_label"] == 1
        assert annotations[0]["predicted_score"] == 0.97
        assert annotations[0]["note_id"] == note.id

        results = await export_results(db, project.id)
        assert len(results) == 1
        assert results[0]["patient_id"] == "external-patient-1"
        assert results[0]["event_information"]["annotation_id"] == current_annotation.annotation_id
        assert "external-patient-1" in format_results_csv(results)

        refreshed = await refresh_project_results(db, project.id)
        assert len(refreshed) == 1
        assert refreshed[0].id == result.id
        count = await db.scalar(
            select(func.count()).select_from(type(result)).where(
                type(result).project_id == project.id
            )
        )
        assert count == 1
