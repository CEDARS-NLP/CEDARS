from datetime import date

import pytest
from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel

from app.annotations.models import Annotation, ReviewStatus
from app.auth.models import User
from app.connectors.models import Patient
from app.production.models import (
    NotePrediction,
    ProductionResult,
    ProductionRun,
    ProductionState,
)
from app.projects.models import Project


def test_production_models_are_registered_and_annotation_matches_physical_contract():
    assert {"production_runs", "production_states", "note_predictions", "RESULTS"} <= set(
        SQLModel.metadata.tables
    )
    table = Annotation.__table__
    assert table.name == "Annotations"
    assert table.primary_key.columns.keys() == ["annotation_id"]
    assert table.c.annotation_id.type.python_type is int
    assert table.c.text_date.type.python_type is date
    assert table.c.status.type.length == 1
    assert all(
        table.c[field].nullable is False
        for field in (
            "text_id", "patient_id", "text_date", "sentence", "token", "isNegated",
            "note_start_index", "note_end_index", "sentence_number", "sentence_start",
            "sentence_end", "status",
        )
    )
    assert not {"event_date", "predicted_score", "predicted_label", "reasoning"} & set(
        table.c.keys()
    )

    fk_targets = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert ("patients.project_id", "patients.patient_id_ext") in fk_targets
    assert (
        "notes.project_id", "notes.text_id", "notes.patient_id_ext"
    ) in fk_targets


def test_annotation_compatibility_aliases_map_to_physical_fields():
    annotation = Annotation(
        annotation_id=17,
        project_id="project",
        text_id="external-note",
        patient_id="external-patient",
        text_date=date(2025, 4, 3),
        sentence="No event found.",
        token="event",
        isNegated=True,
        note_start_index=3,
        note_end_index=8,
        sentence_number=0,
        sentence_start=0,
        sentence_end=15,
        status="U",
    )
    assert annotation.id == 17
    assert annotation.sentence_text == annotation.sentence
    assert annotation.is_negated is True
    assert annotation.review_status is ReviewStatus.UNREVIEWED
    annotation.review_status = ReviewStatus.REVIEWED
    assert annotation.status == "R"


@pytest.mark.asyncio
async def test_patient_event_requires_date_annotation_and_reviewer(session_factory):
    async with session_factory() as session:
        user = User(email="schema@example.test", name="Schema", password_hash="unused")
        session.add(user)
        await session.flush()
        project = Project(name="Schema", owner_id=user.id)
        session.add(project)
        await session.flush()
        session.add(
            Patient(
                project_id=project.id,
                patient_id_ext="external-patient",
                event_date=date(2025, 4, 3),
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


def test_production_prediction_and_result_do_not_store_machine_event_dates():
    assert "event_date" not in NotePrediction.__table__.c
    assert "event_date" in ProductionResult.__table__.c
    assert ProductionRun.__table__.c.config_snapshot.nullable is False
    assert ProductionState.__table__.primary_key.columns.keys() == ["project_id"]
