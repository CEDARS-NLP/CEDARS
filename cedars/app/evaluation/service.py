"""Evaluation service - business logic for LLM prompt evaluation.

This module provides the core service functions for:
1. Keyword-based stratified sampling of clinical notes
2. LLM prediction execution
3. Metrics computation (accuracy, precision, recall, F1)
4. Session and prompt management
"""

from datetime import datetime, timezone
import random
import re
from typing import Optional

from loguru import logger

from app.database import mongo
from app.evaluation.models import (
    EvaluationJudgment,
    EvaluationMetrics,
    EvaluationSession,
    LLMPrediction,
    SampleConfig,
    ValidatedPrompt,
)
from app.models.project import EventDefinitionModel, LLMConfigModel
from app.predictors.config import (
    EventDefinition,
    LLMConfig,
    LLMProvider,
    PredictorConfig,
    PredictorType,
)
from app.predictors.factory import get_predictor
from app.repositories.mongo.evaluation_repository import MongoEvaluationRepository


def _get_repository() -> MongoEvaluationRepository:
    """Get the evaluation repository instance."""
    return MongoEvaluationRepository()


def _convert_llm_config(llm_config: LLMConfigModel) -> LLMConfig:
    """Convert LLMConfigModel to LLMConfig for predictor."""
    return LLMConfig(
        provider=LLMProvider(llm_config.provider),
        model=llm_config.model,
        api_base=llm_config.api_base,
        api_key_env=llm_config.api_key_env,
        timeout=llm_config.timeout,
        temperature=llm_config.temperature,
    )


def _convert_event_definition(event_def: EventDefinitionModel) -> EventDefinition:
    """Convert EventDefinitionModel to EventDefinition for predictor."""
    return EventDefinition(
        name=event_def.name,
        description=event_def.description,
        include_criteria=event_def.include_criteria,
        exclude_criteria=event_def.exclude_criteria,
    )


def _sample_notes_with_keywords(
    sample_config: SampleConfig,
    project_id: Optional[str] = None,
) -> list[str]:
    """Sample notes using keyword-based stratification.

    Args:
        sample_config: Configuration for sampling (size, keywords, ratio).
        project_id: Optional project ID to filter notes.

    Returns:
        List of sampled note IDs (text_id values).
    """
    notes_collection = mongo.db["NOTES"]
    keywords = sample_config.keywords
    total_size = sample_config.size
    keyword_ratio = sample_config.keyword_match_ratio

    # Calculate bucket sizes
    keyword_sample_size = int(total_size * keyword_ratio)

    keyword_matched_ids = []
    non_keyword_ids = []

    # Build base query with project_id filter for data isolation
    base_query = {}
    if project_id:
        base_query["project_id"] = project_id

    if keywords:
        # Build case-insensitive regex pattern for keyword matching
        # Match any keyword in the note text
        keyword_pattern = "|".join(re.escape(kw) for kw in keywords)
        keyword_regex = {"$regex": keyword_pattern, "$options": "i"}

        # Find notes containing any keyword (filtered by project)
        keyword_query = {**base_query, "text": keyword_regex}
        keyword_cursor = notes_collection.find(
            keyword_query,
            {"text_id": 1, "_id": 0}
        )
        keyword_matched_ids = [doc["text_id"] for doc in keyword_cursor]
        logger.info(f"Found {len(keyword_matched_ids)} notes matching keywords")

        # Find notes NOT containing keywords (filtered by project)
        non_keyword_query = {**base_query, "text": {"$not": keyword_regex}}
        non_keyword_cursor = notes_collection.find(
            non_keyword_query,
            {"text_id": 1, "_id": 0}
        )
        non_keyword_ids = [doc["text_id"] for doc in non_keyword_cursor]
        logger.info(f"Found {len(non_keyword_ids)} notes not matching keywords")
    else:
        # No keywords - get all notes (filtered by project)
        cursor = notes_collection.find(base_query, {"text_id": 1, "_id": 0})
        non_keyword_ids = [doc["text_id"] for doc in cursor]
        keyword_sample_size = 0

    # Sample from each bucket
    sampled_ids = []

    # Sample from keyword matches
    if keyword_matched_ids and keyword_sample_size > 0:
        sample_count = min(keyword_sample_size, len(keyword_matched_ids))
        sampled_ids.extend(random.sample(keyword_matched_ids, sample_count))
        logger.info(f"Sampled {sample_count} notes from keyword matches")

    # Fill remaining with non-keyword notes
    remaining_needed = total_size - len(sampled_ids)
    if non_keyword_ids and remaining_needed > 0:
        sample_count = min(remaining_needed, len(non_keyword_ids))
        sampled_ids.extend(random.sample(non_keyword_ids, sample_count))
        logger.info(f"Sampled {sample_count} notes from non-keyword pool")

    # If we still don't have enough, backfill from keyword matches
    if len(sampled_ids) < total_size and keyword_matched_ids:
        already_sampled = set(sampled_ids)
        available = [nid for nid in keyword_matched_ids if nid not in already_sampled]
        remaining_needed = total_size - len(sampled_ids)
        if available:
            sample_count = min(remaining_needed, len(available))
            sampled_ids.extend(random.sample(available, sample_count))
            logger.info(f"Backfilled {sample_count} additional notes from keywords")

    logger.info(f"Total sampled: {len(sampled_ids)} notes for evaluation")
    return sampled_ids


def create_session(
    project_id: str,
    sample_config: SampleConfig,
    llm_config: LLMConfigModel,
    event_definition: EventDefinitionModel,
    created_by: str,
) -> str:
    """Create evaluation session and sample notes using keyword stratification.

    Args:
        project_id: The project ID for this evaluation session.
        sample_config: Configuration for sampling (size, keywords, ratio).
        llm_config: LLM configuration for predictions.
        event_definition: Event definition for classification.
        created_by: Username of the person creating the session.

    Returns:
        The ID of the created evaluation session.
    """
    repo = _get_repository()

    # Sample notes using keyword stratification
    sampled_note_ids = _sample_notes_with_keywords(sample_config, project_id)

    # Create the session
    session = EvaluationSession(
        project_id=project_id,
        created_by=created_by,
        created_at=datetime.now(timezone.utc),
        status="sampling",
        sample_config=sample_config,
        sampled_note_ids=sampled_note_ids,
        llm_config=llm_config,
        event_definition=event_definition,
        metrics=None,
    )

    session_id = repo.create_session(session)
    logger.info(
        f"Created evaluation session {session_id} with {len(sampled_note_ids)} notes"
    )

    return session_id


def run_predictions(session_id: str) -> None:
    """Run LLM predictions on sampled notes (background RQ job).

    This function:
    1. Updates session status to 'running'
    2. Creates a predictor from the session's LLM config
    3. Runs predictions on each sampled note
    4. Stores results as EvaluationJudgment records (without human judgment)
    5. Updates session status to 'reviewing' when complete

    Args:
        session_id: The evaluation session ID.

    Raises:
        ValueError: If the session is not found.
    """
    repo = _get_repository()
    notes_collection = mongo.db["NOTES"]

    # Get the session
    session = repo.get_session(session_id)
    if session is None:
        raise ValueError(f"Evaluation session {session_id} not found")

    # Update status to running
    repo.update_session_status(session_id, "running")
    logger.info(f"Starting predictions for session {session_id}")

    # Build predictor config from session settings
    predictor_config = PredictorConfig(
        predictor_type=PredictorType.LLM,
        llm_config=_convert_llm_config(session.llm_config),
        event_definition=_convert_event_definition(session.event_definition),
    )

    # Create predictor
    predictor = get_predictor(predictor_config)

    # Process each sampled note
    for idx, note_id in enumerate(session.sampled_note_ids):
        try:
            # Get note text from database
            note_doc = notes_collection.find_one({"text_id": note_id})
            if note_doc is None:
                logger.warning(f"Note {note_id} not found, skipping")
                continue

            note_text = note_doc.get("text", "")
            if not note_text:
                logger.warning(f"Note {note_id} has no text, skipping")
                continue

            # Run prediction
            result = predictor.predict(note_text)

            # Create judgment record (without human judgment yet)
            llm_prediction = LLMPrediction(
                label=result.label,
                score=result.score,
                reasoning=result.reasoning or "",
            )

            judgment = EvaluationJudgment(
                session_id=session_id,
                note_id=note_id,
                note_text=note_text,
                llm_prediction=llm_prediction,
                judgment="skipped",  # Will be updated by clinician
                judged_by="",  # Will be set when clinician judges
                judged_at=None,  # Will be set when clinician judges
            )

            repo.create_judgment(judgment)
            logger.debug(
                f"Processed note {idx + 1}/{len(session.sampled_note_ids)}: "
                f"{note_id} -> label={result.label}, score={result.score:.3f}"
            )

        except Exception as e:
            logger.error(f"Error processing note {note_id}: {e}")
            # Continue with next note rather than failing entire batch

    # Update status to reviewing
    repo.update_session_status(session_id, "reviewing")
    logger.info(f"Completed predictions for session {session_id}")


def get_next_for_review(session_id: str) -> Optional[EvaluationJudgment]:
    """Get next un-reviewed note for the review interface.

    Args:
        session_id: The evaluation session ID.

    Returns:
        The next EvaluationJudgment needing review, or None if all reviewed.
    """
    repo = _get_repository()
    return repo.get_next_unjudged(session_id)


def record_judgment(
    session_id: str,
    note_id: str,
    judgment: str,
    user_id: str,
) -> None:
    """Store clinician judgment and update session metrics.

    Args:
        session_id: The evaluation session ID.
        note_id: The note ID being judged.
        judgment: The judgment value ('correct', 'wrong', or 'skipped').
        user_id: The username of the person making the judgment.

    Raises:
        ValueError: If judgment is not a valid value.
    """
    if judgment not in ("correct", "wrong", "skipped"):
        raise ValueError(f"Invalid judgment value: {judgment}")

    repo = _get_repository()

    # Update the judgment
    success = repo.update_judgment(session_id, note_id, judgment, user_id)
    if not success:
        logger.warning(
            f"Failed to update judgment for session={session_id}, note={note_id}"
        )
        return

    logger.info(
        f"Recorded judgment '{judgment}' for note {note_id} in session {session_id}"
    )

    # Recompute and update session metrics
    metrics = compute_metrics(session_id)
    repo.update_session_metrics(session_id, metrics)


def compute_metrics(session_id: str) -> EvaluationMetrics:
    """Calculate accuracy, precision, recall, F1 from judgments.

    For the metrics calculation:
    - True Positive (TP): LLM predicted positive (label=1) AND clinician said 'correct'
    - False Positive (FP): LLM predicted positive (label=1) AND clinician said 'wrong'
    - True Negative (TN): LLM predicted negative (label=0) AND clinician said 'correct'
    - False Negative (FN): LLM predicted negative (label=0) AND clinician said 'wrong'

    Args:
        session_id: The evaluation session ID.

    Returns:
        Computed evaluation metrics.
    """
    repo = _get_repository()

    # Get all judgments for the session
    judgments = repo.get_judgments_by_session(session_id)

    # Count by judgment type
    reviewed = 0
    correct = 0
    wrong = 0
    skipped = 0

    # For precision/recall calculation
    tp = 0  # LLM positive, clinician correct
    fp = 0  # LLM positive, clinician wrong
    tn = 0  # LLM negative, clinician correct
    fn = 0  # LLM negative, clinician wrong

    for j in judgments:
        if j.judged_at is None:
            # Not yet judged
            continue

        if j.judgment == "skipped":
            skipped += 1
            continue

        reviewed += 1
        llm_positive = j.llm_prediction.label == 1

        if j.judgment == "correct":
            correct += 1
            if llm_positive:
                tp += 1
            else:
                tn += 1
        elif j.judgment == "wrong":
            wrong += 1
            if llm_positive:
                fp += 1
            else:
                fn += 1

    # Calculate metrics
    accuracy = 0.0
    precision = 0.0
    recall = 0.0
    f1 = 0.0

    if reviewed > 0:
        accuracy = correct / reviewed

    # Precision = TP / (TP + FP)
    if (tp + fp) > 0:
        precision = tp / (tp + fp)

    # Recall = TP / (TP + FN)
    if (tp + fn) > 0:
        recall = tp / (tp + fn)

    # F1 = 2 * (precision * recall) / (precision + recall)
    if (precision + recall) > 0:
        f1 = 2 * (precision * recall) / (precision + recall)

    return EvaluationMetrics(
        reviewed=reviewed,
        correct=correct,
        wrong=wrong,
        skipped=skipped,
        accuracy=accuracy,
        precision=precision,
        recall=recall,
        f1=f1,
    )


def get_disagreements(session_id: str) -> list[EvaluationJudgment]:
    """Get all items where LLM prediction was marked wrong.

    These are cases where the clinician disagreed with the LLM's classification.

    Args:
        session_id: The evaluation session ID.

    Returns:
        List of EvaluationJudgment records where judgment='wrong'.
    """
    repo = _get_repository()
    judgments = repo.get_judgments_by_session(session_id)

    return [j for j in judgments if j.judgment == "wrong"]


def validate_prompt(
    session_id: str,
    version_name: str,
    notes: str,
    user_id: str,
) -> str:
    """Save current config as validated prompt, return prompt_id.

    This creates a snapshot of the current session's configuration
    along with its evaluation metrics, marking it as a validated prompt
    that can be used for production inference.

    Args:
        session_id: The evaluation session ID to validate.
        version_name: A human-readable version name (e.g., "v1.0", "MI-detection-final").
        notes: Optional notes about this validated prompt.
        user_id: The username of the person validating.

    Returns:
        The ID of the created validated prompt.

    Raises:
        ValueError: If the session is not found.
    """
    repo = _get_repository()

    # Get the session
    session = repo.get_session(session_id)
    if session is None:
        raise ValueError(f"Evaluation session {session_id} not found")

    # Compute final metrics
    metrics = compute_metrics(session_id)

    # Create validated prompt
    validated_prompt = ValidatedPrompt(
        project_id=session.project_id,
        version_name=version_name,
        notes=notes,
        event_definition=session.event_definition,
        llm_config=session.llm_config,
        evaluation_metrics=metrics,
        evaluation_session_id=session_id,
        validated_by=user_id,
        validated_at=datetime.now(timezone.utc),
        is_active=False,  # Not active by default
    )

    prompt_id = repo.create_validated_prompt(validated_prompt)
    logger.info(
        f"Created validated prompt {prompt_id} from session {session_id} "
        f"(accuracy={metrics.accuracy:.2%}, F1={metrics.f1:.2%})"
    )

    # Update session status to completed
    repo.update_session_status(session_id, "completed")
    repo.update_session_metrics(session_id, metrics)

    return prompt_id


def get_active_validated_prompt(project_id: str) -> Optional[ValidatedPrompt]:
    """Get the active validated prompt for a project.

    Args:
        project_id: The project ID.

    Returns:
        The active ValidatedPrompt for the project, or None if none is active.
    """
    repo = _get_repository()
    return repo.get_active_prompt(project_id)


def set_active_prompt(project_id: str, prompt_id: str) -> bool:
    """Set a validated prompt as the active one for a project.

    This deactivates any previously active prompt for the project.

    Args:
        project_id: The project ID.
        prompt_id: The prompt ID to activate.

    Returns:
        True if successful, False otherwise.
    """
    repo = _get_repository()
    success = repo.set_active_prompt(project_id, prompt_id)
    if success:
        logger.info(f"Activated prompt {prompt_id} for project {project_id}")
    return success


def get_session(session_id: str) -> Optional[EvaluationSession]:
    """Get an evaluation session by ID.

    Args:
        session_id: The session ID.

    Returns:
        The EvaluationSession if found, None otherwise.
    """
    repo = _get_repository()
    return repo.get_session(session_id)


def get_sessions_by_project(project_id: str) -> list[EvaluationSession]:
    """Get all evaluation sessions for a project.

    Args:
        project_id: The project ID.

    Returns:
        List of evaluation sessions for the project, sorted by creation date (newest first).
    """
    repo = _get_repository()
    return repo.get_sessions_by_project(project_id)


def get_prompts_by_project(project_id: str) -> list[ValidatedPrompt]:
    """Get all validated prompts for a project.

    Args:
        project_id: The project ID.

    Returns:
        List of validated prompts for the project, sorted by validation date (newest first).
    """
    repo = _get_repository()
    return repo.get_prompts_by_project(project_id)
