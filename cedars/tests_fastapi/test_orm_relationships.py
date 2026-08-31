"""ORM relationship configuration tests."""

from sqlalchemy.orm import configure_mappers

from app.database.global_app_tables import Projects, UserProjectRelation, Users
from app.database.project_table_creation import (
    Annotations,
    Events,
    Notes,
    NotesSummary,
    Patients,
    PINES,
    ProjectUsers,
    Results,
    ReviewerLog,
    Task,
)


def test_orm_relationships_configure():
    """Every bidirectional relationship must configure before endpoint queries run."""
    configure_mappers()

    assert Users.created_projects.property.mapper.class_ is Projects
    assert Users.project_memberships.property.mapper.class_ is UserProjectRelation
    assert Users.memberships_added.property.mapper.class_ is UserProjectRelation
    assert Projects.investigator_user.property.mapper.class_ is Users
    assert Projects.memberships.property.mapper.class_ is UserProjectRelation
    assert UserProjectRelation.project.property.mapper.class_ is Projects
    assert UserProjectRelation.user.property.mapper.class_ is Users
    assert UserProjectRelation.added_by_user.property.mapper.class_ is Users

    assert Patients.notes.property.mapper.class_ is Notes
    assert Patients.notes_summary.property.mapper.class_ is NotesSummary
    assert Patients.annotations.property.mapper.class_ is Annotations
    assert Patients.event.property.mapper.class_ is Events
    assert Patients.pines_predictions.property.mapper.class_ is PINES
    assert Patients.result.property.mapper.class_ is Results
    assert Notes.patient.property.mapper.class_ is Patients
    assert Notes.annotations.property.mapper.class_ is Annotations
    assert Notes.pines_prediction.property.mapper.class_ is PINES
    assert Notes.reviewer_logs.property.mapper.class_ is ReviewerLog
    assert Notes.max_score_results.property.mapper.class_ is Results
    assert NotesSummary.patient.property.mapper.class_ is Patients
    assert Annotations.note.property.mapper.class_ is Notes
    assert Annotations.patient.property.mapper.class_ is Patients
    assert Annotations.event_references.property.mapper.class_ is Events
    assert Annotations.reviewer_logs.property.mapper.class_ is ReviewerLog
    assert Events.patient.property.mapper.class_ is Patients
    assert Events.event_annotation.property.mapper.class_ is Annotations
    assert PINES.patient.property.mapper.class_ is Patients
    assert PINES.note.property.mapper.class_ is Notes
    assert ProjectUsers.results_reviewed.property.mapper.class_ is Results
    assert ProjectUsers.reviewer_logs.property.mapper.class_ is ReviewerLog
    assert ProjectUsers.tasks.property.mapper.class_ is Task
    assert Results.patient.property.mapper.class_ is Patients
    assert Results.max_score_note.property.mapper.class_ is Notes
    assert Results.reviewer_user.property.mapper.class_ is ProjectUsers
    assert ReviewerLog.note.property.mapper.class_ is Notes
    assert ReviewerLog.annotation.property.mapper.class_ is Annotations
    assert ReviewerLog.reviewer_user.property.mapper.class_ is ProjectUsers
    assert Task.user.property.mapper.class_ is ProjectUsers
