"""Flask blueprint for LLM prompt evaluation routes.

This module provides the web interface for:
1. Creating evaluation sessions with keyword-based sampling
2. Running LLM predictions on sampled notes
3. Clinician review and judgment interface
4. Metrics dashboard
5. Validating and exporting prompts
"""

import csv
import io
from datetime import datetime

import flask
from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from loguru import logger

from app import db
from app.evaluation import service
from app.evaluation.models import SampleConfig
from app.models.project import EventDefinitionModel, LLMConfigModel


evaluation_bp = Blueprint(
    "evaluation",
    __name__,
    url_prefix="/project",
    template_folder="../templates/evaluation",
)


def _check_admin_access() -> bool:
    """Check if current user has admin access.

    Returns:
        True if user is admin, False otherwise.
    """
    return db.is_admin_user(current_user.get_id())


@evaluation_bp.route("/<project_id>/evaluation")
@login_required
def index(project_id: str):
    """Main evaluation page showing session list and creation form.

    Displays:
    - List of existing evaluation sessions for this project
    - Form to create a new evaluation session with sampling configuration
    - List of validated prompts

    Args:
        project_id: The project ID to view evaluations for.
    """
    if not _check_admin_access():
        flash("Admin access required to manage evaluations.")
        return redirect(url_for("ops.project_details"))

    # Get existing sessions for this project
    sessions = service.get_sessions_by_project(project_id)

    # Get validated prompts for this project
    validated_prompts = service.get_prompts_by_project(project_id)

    # Get project info for template context
    project_info = db.get_info()

    return render_template(
        "evaluation/index.html",
        sessions=sessions,
        validated_prompts=validated_prompts,
        **project_info,
    )


@evaluation_bp.route("/<project_id>/evaluation/create", methods=["POST"])
@login_required
def create_session(project_id: str):
    """Create a new evaluation session with keyword-based sampling.

    Form data expected:
    - sample_size: Number of notes to sample (20-200)
    - keywords: Comma-separated list of keywords for stratification
    - keyword_ratio: Ratio of keyword-matched notes (0.0-1.0)
    - llm_provider: LLM provider (openai, anthropic, ollama, etc.)
    - llm_model: Model name
    - llm_api_base: Optional API base URL
    - llm_api_key_env: Optional environment variable for API key
    - llm_temperature: Temperature for generation
    - llm_timeout: Request timeout in seconds
    - event_name: Name of the clinical event
    - event_description: Description of the event
    - include_criteria: Criteria for inclusion
    - exclude_criteria: Criteria for exclusion

    Args:
        project_id: The project ID to create evaluation for.
    """
    if not _check_admin_access():
        flash("Admin access required to create evaluations.")
        return redirect(url_for("ops.project_details"))

    try:
        # Parse sample configuration
        sample_size = int(request.form.get("sample_size", 50))
        keywords_str = request.form.get("keywords", "").strip()
        keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
        keyword_ratio = float(request.form.get("keyword_ratio", 0.5))

        sample_config = SampleConfig(
            size=sample_size,
            keywords=keywords,
            keyword_match_ratio=keyword_ratio,
        )

        # Parse LLM configuration
        llm_config = LLMConfigModel(
            provider=request.form.get("llm_provider", "openai"),
            model=request.form.get("llm_model", "gpt-4o"),
            api_base=request.form.get("llm_api_base") or None,
            api_key_env=request.form.get("llm_api_key_env") or None,
            temperature=float(request.form.get("llm_temperature", 0.0)),
            timeout=int(request.form.get("llm_timeout", 60)),
        )

        # Parse event definition
        event_definition = EventDefinitionModel(
            name=request.form.get("event_name", ""),
            description=request.form.get("event_description", ""),
            include_criteria=request.form.get("include_criteria", ""),
            exclude_criteria=request.form.get("exclude_criteria", ""),
        )

        # Create the session
        session_id = service.create_session(
            project_id=project_id,
            sample_config=sample_config,
            llm_config=llm_config,
            event_definition=event_definition,
            created_by=current_user.get_id(),
        )

        flash(f"Evaluation session created with {sample_config.size} sampled notes.")
        logger.info(
            f"Created evaluation session {session_id} for project {project_id} "
            f"by {current_user.get_id()}"
        )

        return redirect(
            url_for("evaluation.session_detail", project_id=project_id, session_id=session_id)
        )

    except ValueError as e:
        flash(f"Invalid configuration: {e}")
        logger.warning(f"Failed to create evaluation session: {e}")
        return redirect(url_for("evaluation.index", project_id=project_id))

    except Exception as e:
        flash(f"Failed to create evaluation session: {e}")
        logger.error(f"Error creating evaluation session: {e}")
        return redirect(url_for("evaluation.index", project_id=project_id))


@evaluation_bp.route("/<project_id>/evaluation/<session_id>")
@login_required
def session_detail(project_id: str, session_id: str):
    """Session detail page showing configuration and status.

    Displays:
    - Session configuration (sampling, LLM config, event definition)
    - Current status (sampling, running, reviewing, completed)
    - Metrics summary if available
    - Actions based on status (run predictions, review, validate)

    Args:
        project_id: The project ID.
        session_id: The evaluation session ID.
    """
    if not _check_admin_access():
        flash("Admin access required to view evaluations.")
        return redirect(url_for("ops.project_details"))

    session = service.get_session(session_id)
    if session is None:
        flash("Evaluation session not found.")
        return redirect(url_for("evaluation.index", project_id=project_id))

    # Verify session belongs to the correct project
    if session.project_id != project_id:
        flash("Session does not belong to this project.")
        return redirect(url_for("evaluation.index", project_id=project_id))

    # Get disagreements if in reviewing or completed status
    disagreements = []
    if session.status in ("reviewing", "completed"):
        disagreements = service.get_disagreements(session_id)

    project_info = db.get_info()

    return render_template(
        "evaluation/session_detail.html",
        session=session,
        disagreements=disagreements,
        **project_info,
    )


@evaluation_bp.route("/<project_id>/evaluation/<session_id>/run", methods=["POST"])
@login_required
def run_predictions(project_id: str, session_id: str):
    """Start running LLM predictions on sampled notes.

    This enqueues a background job to process all sampled notes.

    Args:
        project_id: The project ID.
        session_id: The evaluation session ID.
    """
    if not _check_admin_access():
        flash("Admin access required to run predictions.")
        return redirect(url_for("ops.project_details"))

    session = service.get_session(session_id)
    if session is None:
        flash("Evaluation session not found.")
        return redirect(url_for("evaluation.index", project_id=project_id))

    if session.project_id != project_id:
        flash("Session does not belong to this project.")
        return redirect(url_for("evaluation.index", project_id=project_id))

    if session.status not in ("sampling",):
        flash(
            f"Cannot run predictions in status '{session.status}'. "
            "Session must be in 'sampling' status."
        )
        return redirect(
            url_for("evaluation.session_detail", project_id=project_id, session_id=session_id)
        )

    try:
        # Enqueue background job for predictions
        job = flask.current_app.ops_queue.enqueue(
            service.run_predictions,
            session_id,
            job_id=f"eval-predictions-{session_id}",
        )

        flash(f"Prediction job started. Job ID: {job.get_id()}")
        logger.info(
            f"Started prediction job {job.get_id()} for session {session_id}"
        )

    except Exception as e:
        flash(f"Failed to start predictions: {e}")
        logger.error(f"Error starting predictions for session {session_id}: {e}")

    return redirect(
        url_for("evaluation.session_detail", project_id=project_id, session_id=session_id)
    )


@evaluation_bp.route("/<project_id>/evaluation/<session_id>/review")
@login_required
def review(project_id: str, session_id: str):
    """Review interface for clinician judgment.

    Displays the next un-reviewed note with LLM prediction for judgment.

    Args:
        project_id: The project ID.
        session_id: The evaluation session ID.
    """
    if not _check_admin_access():
        flash("Admin access required to review evaluations.")
        return redirect(url_for("ops.project_details"))

    session = service.get_session(session_id)
    if session is None:
        flash("Evaluation session not found.")
        return redirect(url_for("evaluation.index", project_id=project_id))

    if session.project_id != project_id:
        flash("Session does not belong to this project.")
        return redirect(url_for("evaluation.index", project_id=project_id))

    if session.status not in ("reviewing", "completed"):
        flash(f"Cannot review in status '{session.status}'. Run predictions first.")
        return redirect(
            url_for("evaluation.session_detail", project_id=project_id, session_id=session_id)
        )

    # Get next un-reviewed item
    judgment = service.get_next_for_review(session_id)

    if judgment is None:
        flash("All notes have been reviewed. You can validate the prompt now.")
        return redirect(
            url_for("evaluation.session_detail", project_id=project_id, session_id=session_id)
        )

    # Compute current progress
    metrics = service.compute_metrics(session_id)
    total_notes = len(session.sampled_note_ids)
    reviewed_count = metrics.reviewed + metrics.skipped
    percent = (reviewed_count / total_notes * 100) if total_notes > 0 else 0
    progress = {
        "reviewed": reviewed_count,
        "total": total_notes,
        "percent": percent,
    }

    project_info = db.get_info()

    return render_template(
        "evaluation/review.html",
        session_id=session_id,
        session=session,
        judgment=judgment,
        progress=progress,
        metrics=metrics,
        **project_info,
    )


@evaluation_bp.route("/<project_id>/evaluation/<session_id>/review", methods=["POST"])
@login_required
def submit_judgment(project_id: str, session_id: str):
    """Submit a clinician judgment for a note.

    Form data expected:
    - note_id: The note being judged
    - judgment: 'correct', 'wrong', or 'skipped'

    Args:
        project_id: The project ID.
        session_id: The evaluation session ID.
    """
    if not _check_admin_access():
        flash("Admin access required to submit judgments.")
        return redirect(url_for("ops.project_details"))

    session = service.get_session(session_id)
    if session is None:
        flash("Evaluation session not found.")
        return redirect(url_for("evaluation.index", project_id=project_id))

    if session.project_id != project_id:
        flash("Session does not belong to this project.")
        return redirect(url_for("evaluation.index", project_id=project_id))

    note_id = request.form.get("note_id")
    judgment = request.form.get("judgment")

    if not note_id or not judgment:
        flash("Missing note_id or judgment.")
        return redirect(
            url_for("evaluation.review", project_id=project_id, session_id=session_id)
        )

    if judgment not in ("correct", "wrong", "skipped"):
        flash(f"Invalid judgment: {judgment}")
        return redirect(
            url_for("evaluation.review", project_id=project_id, session_id=session_id)
        )

    try:
        service.record_judgment(
            session_id=session_id,
            note_id=note_id,
            judgment=judgment,
            user_id=current_user.get_id(),
        )

        logger.debug(
            f"Recorded judgment '{judgment}' for note {note_id} in session {session_id}"
        )

    except ValueError as e:
        flash(f"Invalid judgment: {e}")
        logger.warning(f"Failed to record judgment: {e}")

    except Exception as e:
        flash(f"Failed to record judgment: {e}")
        logger.error(f"Error recording judgment: {e}")

    # Redirect back to review page for next item
    return redirect(
        url_for("evaluation.review", project_id=project_id, session_id=session_id)
    )


@evaluation_bp.route("/<project_id>/evaluation/<session_id>/dashboard")
@login_required
def dashboard(project_id: str, session_id: str):
    """Metrics dashboard showing evaluation results.

    Displays:
    - Accuracy, precision, recall, F1 scores
    - Confusion matrix summary
    - List of disagreements (wrong predictions)

    Args:
        project_id: The project ID.
        session_id: The evaluation session ID.
    """
    if not _check_admin_access():
        flash("Admin access required to view dashboard.")
        return redirect(url_for("ops.project_details"))

    session = service.get_session(session_id)
    if session is None:
        flash("Evaluation session not found.")
        return redirect(url_for("evaluation.index", project_id=project_id))

    if session.project_id != project_id:
        flash("Session does not belong to this project.")
        return redirect(url_for("evaluation.index", project_id=project_id))

    # Compute fresh metrics
    metrics = service.compute_metrics(session_id)

    # Get disagreements for analysis
    disagreements = service.get_disagreements(session_id)

    project_info = db.get_info()

    return render_template(
        "evaluation/dashboard.html",
        session_id=session_id,
        session=session,
        metrics=metrics,
        disagreements=disagreements,
        **project_info,
    )


@evaluation_bp.route("/<project_id>/evaluation/<session_id>/validate", methods=["POST"])
@login_required
def validate(project_id: str, session_id: str):
    """Save the current configuration as a validated prompt.

    Form data expected:
    - version_name: Human-readable version name
    - notes: Optional notes about the validated prompt

    Args:
        project_id: The project ID.
        session_id: The evaluation session ID.
    """
    if not _check_admin_access():
        flash("Admin access required to validate prompts.")
        return redirect(url_for("ops.project_details"))

    session = service.get_session(session_id)
    if session is None:
        flash("Evaluation session not found.")
        return redirect(url_for("evaluation.index", project_id=project_id))

    if session.project_id != project_id:
        flash("Session does not belong to this project.")
        return redirect(url_for("evaluation.index", project_id=project_id))

    version_name = request.form.get("version_name", "").strip()
    notes = request.form.get("notes", "").strip()

    if not version_name:
        flash("Version name is required.")
        return redirect(
            url_for("evaluation.session_detail", project_id=project_id, session_id=session_id)
        )

    try:
        prompt_id = service.validate_prompt(
            session_id=session_id,
            version_name=version_name,
            notes=notes,
            user_id=current_user.get_id(),
        )

        flash(f"Prompt validated successfully. Prompt ID: {prompt_id}")
        logger.info(
            f"Validated prompt {prompt_id} from session {session_id} "
            f"by {current_user.get_id()}"
        )

    except ValueError as e:
        flash(f"Validation failed: {e}")
        logger.warning(f"Failed to validate prompt: {e}")
        return redirect(
            url_for("evaluation.session_detail", project_id=project_id, session_id=session_id)
        )

    except Exception as e:
        flash(f"Failed to validate prompt: {e}")
        logger.error(f"Error validating prompt: {e}")
        return redirect(
            url_for("evaluation.session_detail", project_id=project_id, session_id=session_id)
        )

    return redirect(url_for("evaluation.index", project_id=project_id))


@evaluation_bp.route("/<project_id>/evaluation/<session_id>/export")
@login_required
def export_csv(project_id: str, session_id: str):
    """Export evaluation results as CSV.

    The CSV contains:
    - note_id: The note identifier
    - note_text: The clinical note text
    - llm_label: LLM prediction label (0 or 1)
    - llm_score: LLM confidence score
    - llm_reasoning: LLM reasoning for prediction
    - judgment: Clinician judgment (correct, wrong, skipped)
    - judged_by: Username of clinician
    - judged_at: Timestamp of judgment

    Args:
        project_id: The project ID.
        session_id: The evaluation session ID.
    """
    if not _check_admin_access():
        flash("Admin access required to export data.")
        return redirect(url_for("ops.project_details"))

    session = service.get_session(session_id)
    if session is None:
        flash("Evaluation session not found.")
        return redirect(url_for("evaluation.index", project_id=project_id))

    if session.project_id != project_id:
        flash("Session does not belong to this project.")
        return redirect(url_for("evaluation.index", project_id=project_id))

    # Get repository to fetch all judgments
    from app.repositories.mongo.evaluation_repository import MongoEvaluationRepository
    repo = MongoEvaluationRepository()
    judgments = repo.get_judgments_by_session(session_id)

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow([
        "note_id",
        "note_text",
        "llm_label",
        "llm_score",
        "llm_reasoning",
        "judgment",
        "judged_by",
        "judged_at",
    ])

    # Write data rows
    for j in judgments:
        writer.writerow([
            j.note_id,
            j.note_text,
            j.llm_prediction.label,
            j.llm_prediction.score,
            j.llm_prediction.reasoning,
            j.judgment,
            j.judged_by,
            j.judged_at.isoformat() if j.judged_at else "",
        ])

    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"evaluation_{session_id}_{timestamp}.csv"

    # Return as downloadable file
    output.seek(0)
    return flask.Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"},
    )


@evaluation_bp.route("/<project_id>/evaluation/prompts/<prompt_id>/activate", methods=["POST"])
@login_required
def activate_prompt(project_id: str, prompt_id: str):
    """Activate a validated prompt for production use.

    Args:
        project_id: The project ID.
        prompt_id: The validated prompt ID to activate.
    """
    if not _check_admin_access():
        flash("Admin access required to activate prompts.")
        return redirect(url_for("ops.project_details"))

    try:
        success = service.set_active_prompt(project_id, prompt_id)

        if success:
            flash(f"Prompt {prompt_id} activated for production use.")
            logger.info(
                f"Activated prompt {prompt_id} for project {project_id} "
                f"by {current_user.get_id()}"
            )
        else:
            flash("Failed to activate prompt.")
            logger.warning(f"Failed to activate prompt {prompt_id}")

    except Exception as e:
        flash(f"Failed to activate prompt: {e}")
        logger.error(f"Error activating prompt {prompt_id}: {e}")

    return redirect(url_for("evaluation.index", project_id=project_id))
