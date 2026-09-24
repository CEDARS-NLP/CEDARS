"""Paginated project-local patient queries for the Patients workspace."""
from sqlalchemy import func, select

from .db_session import session_scope
from .project_table_creation import Annotations, Notes, Patients


WORKFLOW_STATUSES = {"new", "nlp_processing", "nlp_complete", "reviewing", "reviewed"}


def patient_workflow_status(patient) -> str:
    """Map legacy patient state while favoring the post-cutover workflow state."""
    if patient.workflow_status in WORKFLOW_STATUSES:
        return patient.workflow_status
    if patient.reviewed:
        return "reviewed"
    if patient.pines_status == "running":
        return "nlp_processing"
    if patient.pines_status == "succeeded":
        return "nlp_complete"
    if patient.locked:
        return "reviewing"
    return "new"


def list_patients(project_engine, limit: int, offset: int,
                  search: str | None = None, status: str | None = None) -> tuple[list[dict], int]:
    """Return one project's patients and computed review counts in stable order."""
    with session_scope(project_engine) as session:
        criteria = []
        if search:
            criteria.append(Patients.patient_id.ilike(f"%{search.strip()}%"))

        base = select(Patients)
        if criteria:
            base = base.where(*criteria)
        patients = list(session.scalars(
            base.order_by(Patients.index_no, Patients.patient_id).offset(offset).limit(limit)
        ))

        total = session.scalar(select(func.count()).select_from(Patients).where(*criteria)) or 0

        if status:
            patients = [patient for patient in patients if patient_workflow_status(patient) == status]
            # Workflow status can be compatibility-derived, so filter/count in Python
            # until every historical record is migrated to an explicit status.
            all_patients = list(session.scalars(base.order_by(Patients.index_no, Patients.patient_id)))
            matching = [patient for patient in all_patients if patient_workflow_status(patient) == status]
            total = len(matching)
            patients = matching[offset:offset + limit]

        patient_ids = [patient.patient_id for patient in patients]
        if not patient_ids:
            return [], total

        note_counts = dict(session.execute(
            select(Notes.patient_id, func.count())
            .where(Notes.patient_id.in_(patient_ids))
            .group_by(Notes.patient_id)
        ).all())
        annotation_counts = dict(session.execute(
            select(Annotations.patient_id, func.count())
            .where(Annotations.patient_id.in_(patient_ids))
            .group_by(Annotations.patient_id)
        ).all())
        reviewed_counts = dict(session.execute(
            select(Annotations.patient_id, func.count())
            .where(
                Annotations.patient_id.in_(patient_ids),
                Annotations.status == Annotations.STATUS_REVIEWED,
            )
            .group_by(Annotations.patient_id)
        ).all())

    return [
        {
            "id": patient.patient_id,
            "patient_id_ext": patient.patient_id,
            "status": patient_workflow_status(patient),
            "note_count": note_counts.get(patient.patient_id, 0),
            "annotation_count": annotation_counts.get(patient.patient_id, 0),
            "reviewed_count": reviewed_counts.get(patient.patient_id, 0),
            "created_at": patient.created_at,
            "updated_at": patient.updated_at,
        }
        for patient in patients
    ], total