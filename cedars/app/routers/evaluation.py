"""Admin-only evaluation APIs isolated from the annotation workflow."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from ..database import get_current_project_engine
from ..database.db_projects import get_pines_url, is_pines_api_running
from ..database.db_session import session_scope
from ..database.external_services import get_prediction
from ..database.project_table_creation import (
    EvaluationSessions,
    LLMEvaluationResults,
    Notes,
    Patients,
)
from ..dependencies import ProjectContext, require_project_admin
from ..schemas import (
    EvaluationJudgmentRequest,
    EvaluationMetricsOut,
    EvaluationNoteOut,
    EvaluationPatientOut,
    EvaluationRunRequest,
    EvaluationSessionCreate,
    EvaluationSessionOut,
    LLMEvaluationResultOut,
)

router = APIRouter(prefix="/projects/{project_id}/evaluation", tags=["evaluation"])
_MAX_RUN_NOTES = 50


def _session_or_404(session, eval_session_id: str) -> EvaluationSessions:
    evaluation = session.get(EvaluationSessions, eval_session_id)
    if evaluation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Evaluation session not found")
    return evaluation


@router.get("/patients", response_model=list[EvaluationPatientOut])
def list_patients(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _ctx: ProjectContext = Depends(require_project_admin),
):
    """Read patient identifiers and note counts without changing workflow data."""
    engine = get_current_project_engine()
    with session_scope(engine) as session:
        rows = session.execute(
            select(Patients.patient_id, func.count(Notes.text_id))
            .outerjoin(Notes, Notes.patient_id == Patients.patient_id)
            .group_by(Patients.patient_id)
            .order_by(Patients.patient_id)
            .limit(limit)
            .offset(offset)
        ).all()
    return [EvaluationPatientOut(patient_id=row[0], note_count=row[1]) for row in rows]


@router.get("/patients/{patient_id}/notes", response_model=list[EvaluationNoteOut])
def list_patient_notes(
    patient_id: str,
    _ctx: ProjectContext = Depends(require_project_admin),
):
    """Read a patient's notes for isolated evaluation input."""
    with session_scope(get_current_project_engine()) as session:
        if session.get(Patients, patient_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Patient not found")
        notes = session.scalars(
            select(Notes).where(Notes.patient_id == patient_id)
            .order_by(Notes.text_date, Notes.text_id)
        ).all()
        return [EvaluationNoteOut(
            note_id=note.text_id,
            patient_id=note.patient_id,
            note_date=note.text_date,
            text=note.text,
        ) for note in notes]


@router.post("/sessions", response_model=EvaluationSessionOut,
             status_code=status.HTTP_201_CREATED)
def create_session(
    request: EvaluationSessionCreate,
    ctx: ProjectContext = Depends(require_project_admin),
):
    """Create an evaluation session without changing project workflow records."""
    patient_ids = list(dict.fromkeys(request.sample_patient_ids))
    if not request.event_name.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Event name is required")
    if not patient_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Select at least one patient")
    if len(patient_ids) > 100:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Select no more than 100 patients")

    engine = get_current_project_engine()
    with session_scope(engine) as session:
        existing = set(session.scalars(
            select(Patients.patient_id).where(Patients.patient_id.in_(patient_ids))
        ))
        if existing != set(patient_ids):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="One or more selected patients do not exist")
        evaluation = EvaluationSessions(
            eval_session_id=str(uuid4()),
            event_name=request.event_name.strip(),
            event_description=request.event_description,
            include_criteria=request.include_criteria,
            exclude_criteria=request.exclude_criteria,
            search_queries=request.search_queries,
            sample_patient_ids=patient_ids,
            metrics={},
            status="draft",
            created_by=ctx.user.username,
        )
        session.add(evaluation)
        session.flush()
        return EvaluationSessionOut.model_validate(evaluation, from_attributes=True)


@router.get("/sessions", response_model=list[EvaluationSessionOut])
def list_sessions(_ctx: ProjectContext = Depends(require_project_admin)):
    with session_scope(get_current_project_engine()) as session:
        evaluations = session.scalars(
            select(EvaluationSessions).order_by(EvaluationSessions.created_at.desc())
        ).all()
        return [EvaluationSessionOut.model_validate(item, from_attributes=True)
                for item in evaluations]


@router.get("/sessions/{eval_session_id}", response_model=EvaluationSessionOut)
def get_session(
    eval_session_id: str,
    _ctx: ProjectContext = Depends(require_project_admin),
):
    with session_scope(get_current_project_engine()) as session:
        evaluation = _session_or_404(session, eval_session_id)
        return EvaluationSessionOut.model_validate(evaluation, from_attributes=True)


@router.get("/sessions/{eval_session_id}/notes", response_model=list[EvaluationNoteOut])
def list_session_notes(
    eval_session_id: str,
    _ctx: ProjectContext = Depends(require_project_admin),
):
    """Read notes for this evaluation's selected patients only."""
    with session_scope(get_current_project_engine()) as session:
        evaluation = _session_or_404(session, eval_session_id)
        notes = session.scalars(
            select(Notes)
            .where(Notes.patient_id.in_(evaluation.sample_patient_ids))
            .order_by(Notes.patient_id, Notes.text_date, Notes.text_id)
        ).all()
        return [EvaluationNoteOut(
            note_id=note.text_id,
            patient_id=note.patient_id,
            note_date=note.text_date,
            text=note.text,
        ) for note in notes]


@router.post("/sessions/{eval_session_id}/run",
             response_model=list[LLMEvaluationResultOut])
def run_evaluation(
    eval_session_id: str,
    request: EvaluationRunRequest,
    _ctx: ProjectContext = Depends(require_project_admin),
):
    """Classify selected notes and persist outputs only in LLMEvaluationResults."""
    note_ids = list(dict.fromkeys(request.note_ids))
    if not note_ids or len(note_ids) > _MAX_RUN_NOTES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Select between 1 and {_MAX_RUN_NOTES} notes")
    engine = get_current_project_engine()
    with session_scope(engine) as session:
        evaluation = _session_or_404(session, eval_session_id)
        if evaluation.status == "completed":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Completed evaluations cannot be changed")
        notes = session.scalars(select(Notes).where(Notes.text_id.in_(note_ids))).all()
        if len(notes) != len(note_ids) or any(
            note.patient_id not in evaluation.sample_patient_ids for note in notes
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Selected notes must belong to this session's patients")
        note_inputs = [(note.text_id, note.patient_id, note.text) for note in notes]

    if not is_pines_api_running(engine):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="PINES is not enabled for this project")
    pines_url = get_pines_url(engine)
    if not pines_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="PINES is not configured for this project")

    predictions = []
    try:
        for note_id, patient_id, note_text in note_inputs:
            score, label, model_name, threshold = get_prediction(pines_url, note_text)
            predictions.append(LLMEvaluationResults(
                evaluation_result_id=str(uuid4()),
                eval_session_id=eval_session_id,
                patient_id=patient_id,
                note_id=note_id,
                model_name=model_name,
                predicted_score=score,
                predicted_label=label,
                classification_threshold=threshold,
                result_json={
                    "score": score,
                    "label": label,
                    "model": model_name,
                    "classification_threshold": threshold,
                },
            ))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="PINES could not evaluate the selected notes") from exc

    with session_scope(engine) as session:
        evaluation = _session_or_404(session, eval_session_id)
        if evaluation.status == "completed":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Completed evaluations cannot be changed")
        session.add_all(predictions)
        evaluation.status = "reviewing"
        evaluation.updated_at = datetime.now(timezone.utc)
        session.flush()
        return [LLMEvaluationResultOut.model_validate(item, from_attributes=True)
                for item in predictions]


@router.get("/sessions/{eval_session_id}/results",
            response_model=list[LLMEvaluationResultOut])
def list_results(
    eval_session_id: str,
    _ctx: ProjectContext = Depends(require_project_admin),
):
    with session_scope(get_current_project_engine()) as session:
        _session_or_404(session, eval_session_id)
        results = session.scalars(
            select(LLMEvaluationResults)
            .where(LLMEvaluationResults.eval_session_id == eval_session_id)
            .order_by(LLMEvaluationResults.evaluated_at, LLMEvaluationResults.note_id)
        ).all()
        return [LLMEvaluationResultOut.model_validate(item, from_attributes=True)
                for item in results]


@router.post("/sessions/{eval_session_id}/results/{result_id}/judge",
             response_model=LLMEvaluationResultOut)
def judge_result(
    eval_session_id: str,
    result_id: str,
    request: EvaluationJudgmentRequest,
    ctx: ProjectContext = Depends(require_project_admin),
):
    if request.judgment not in {"correct", "wrong", "skipped"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Judgment must be correct, wrong, or skipped")
    with session_scope(get_current_project_engine()) as session:
        evaluation = _session_or_404(session, eval_session_id)
        if evaluation.status == "completed":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Completed evaluations cannot be changed")
        result = session.get(LLMEvaluationResults, result_id)
        if result is None or result.eval_session_id != eval_session_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Evaluation result not found")
        result.review_judgment = request.judgment
        result.reviewed_by = ctx.user.username
        result.reviewed_at = datetime.now(timezone.utc)
        session.flush()
        return LLMEvaluationResultOut.model_validate(result, from_attributes=True)


@router.get("/sessions/{eval_session_id}/metrics", response_model=EvaluationMetricsOut)
def get_metrics(
    eval_session_id: str,
    _ctx: ProjectContext = Depends(require_project_admin),
):
    with session_scope(get_current_project_engine()) as session:
        _session_or_404(session, eval_session_id)
        judgments = session.execute(
            select(LLMEvaluationResults.review_judgment)
            .where(LLMEvaluationResults.eval_session_id == eval_session_id)
        ).scalars().all()
    correct = judgments.count("correct")
    incorrect = judgments.count("wrong")
    reviewed = correct + incorrect
    return EvaluationMetricsOut(
        total_results=len(judgments),
        reviewed=reviewed,
        correct=correct,
        incorrect=incorrect,
        skipped=judgments.count("skipped"),
        accuracy=correct / reviewed if reviewed else None,
    )


@router.post("/sessions/{eval_session_id}/finalize",
             response_model=EvaluationSessionOut)
def finalize_session(
    eval_session_id: str,
    _ctx: ProjectContext = Depends(require_project_admin),
):
    """Complete only this evaluation session; no project pipeline is dispatched."""
    with session_scope(get_current_project_engine()) as session:
        evaluation = _session_or_404(session, eval_session_id)
        if evaluation.status == "completed":
            return EvaluationSessionOut.model_validate(evaluation, from_attributes=True)
        evaluation.status = "completed"
        evaluation.updated_at = datetime.now(timezone.utc)
        session.flush()
        return EvaluationSessionOut.model_validate(evaluation, from_attributes=True)