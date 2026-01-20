"""Evaluation repository interface for LLM prompt evaluation system."""

from abc import ABC, abstractmethod
from typing import Optional

from app.evaluation.models import (
    EvaluationSession,
    EvaluationJudgment,
    EvaluationMetrics,
    ValidatedPrompt,
)


class EvaluationRepositoryInterface(ABC):
    """Abstract interface for evaluation data access.

    This interface defines the contract for storing and retrieving
    evaluation sessions, judgments, and validated prompts used in
    the LLM prompt evaluation workflow.
    """

    # -------------------------------------------------------------------------
    # Evaluation Sessions
    # -------------------------------------------------------------------------

    @abstractmethod
    def create_session(self, session: EvaluationSession) -> str:
        """Create a new evaluation session.

        Args:
            session: The evaluation session to create.

        Returns:
            The ID of the created session.
        """
        pass

    @abstractmethod
    def get_session(self, session_id: str) -> Optional[EvaluationSession]:
        """Get an evaluation session by ID.

        Args:
            session_id: The session ID to look up.

        Returns:
            The evaluation session if found, None otherwise.
        """
        pass

    @abstractmethod
    def get_sessions_by_project(self, project_id: str) -> list[EvaluationSession]:
        """Get all evaluation sessions for a project.

        Args:
            project_id: The project ID to filter by.

        Returns:
            List of evaluation sessions for the project.
        """
        pass

    @abstractmethod
    def update_session_status(self, session_id: str, status: str) -> bool:
        """Update the status of an evaluation session.

        Args:
            session_id: The session ID to update.
            status: The new status (sampling, running, reviewing, completed).

        Returns:
            True if the update succeeded, False otherwise.
        """
        pass

    @abstractmethod
    def update_session_metrics(
        self, session_id: str, metrics: EvaluationMetrics
    ) -> bool:
        """Update the metrics for an evaluation session.

        Args:
            session_id: The session ID to update.
            metrics: The computed evaluation metrics.

        Returns:
            True if the update succeeded, False otherwise.
        """
        pass

    @abstractmethod
    def set_sampled_notes(self, session_id: str, note_ids: list[str]) -> bool:
        """Set the sampled note IDs for an evaluation session.

        Args:
            session_id: The session ID to update.
            note_ids: List of note IDs that were sampled.

        Returns:
            True if the update succeeded, False otherwise.
        """
        pass

    # -------------------------------------------------------------------------
    # Evaluation Judgments
    # -------------------------------------------------------------------------

    @abstractmethod
    def create_judgment(self, judgment: EvaluationJudgment) -> str:
        """Create a new evaluation judgment.

        Args:
            judgment: The evaluation judgment to create.

        Returns:
            The ID of the created judgment.
        """
        pass

    @abstractmethod
    def get_judgment(
        self, session_id: str, note_id: str
    ) -> Optional[EvaluationJudgment]:
        """Get an evaluation judgment by session and note ID.

        Args:
            session_id: The session ID.
            note_id: The note ID.

        Returns:
            The evaluation judgment if found, None otherwise.
        """
        pass

    @abstractmethod
    def get_judgments_by_session(self, session_id: str) -> list[EvaluationJudgment]:
        """Get all judgments for an evaluation session.

        Args:
            session_id: The session ID to filter by.

        Returns:
            List of evaluation judgments for the session.
        """
        pass

    @abstractmethod
    def get_next_unjudged(self, session_id: str) -> Optional[EvaluationJudgment]:
        """Get the next note needing human review in a session.

        Args:
            session_id: The session ID to search in.

        Returns:
            The next unjudged evaluation judgment, or None if all are judged.
        """
        pass

    @abstractmethod
    def update_judgment(
        self, session_id: str, note_id: str, judgment: str, judged_by: str
    ) -> bool:
        """Record a human judgment for an LLM prediction.

        Args:
            session_id: The session ID.
            note_id: The note ID.
            judgment: The judgment value (correct, wrong, skipped).
            judged_by: Username of the person making the judgment.

        Returns:
            True if the update succeeded, False otherwise.
        """
        pass

    @abstractmethod
    def count_by_judgment(self, session_id: str) -> dict[str, int]:
        """Count judgments by type for a session.

        Args:
            session_id: The session ID to count.

        Returns:
            Dictionary mapping judgment types to counts.
            Example: {"correct": 10, "wrong": 5, "skipped": 2}
        """
        pass

    # -------------------------------------------------------------------------
    # Validated Prompts
    # -------------------------------------------------------------------------

    @abstractmethod
    def create_validated_prompt(self, prompt: ValidatedPrompt) -> str:
        """Create a new validated prompt.

        Args:
            prompt: The validated prompt to create.

        Returns:
            The ID of the created prompt.
        """
        pass

    @abstractmethod
    def get_validated_prompt(self, prompt_id: str) -> Optional[ValidatedPrompt]:
        """Get a validated prompt by ID.

        Args:
            prompt_id: The prompt ID to look up.

        Returns:
            The validated prompt if found, None otherwise.
        """
        pass

    @abstractmethod
    def get_active_prompt(self, project_id: str) -> Optional[ValidatedPrompt]:
        """Get the active validated prompt for a project.

        Args:
            project_id: The project ID.

        Returns:
            The active validated prompt if one exists, None otherwise.
        """
        pass

    @abstractmethod
    def get_prompts_by_project(self, project_id: str) -> list[ValidatedPrompt]:
        """Get all validated prompts for a project.

        Args:
            project_id: The project ID to filter by.

        Returns:
            List of validated prompts for the project.
        """
        pass

    @abstractmethod
    def set_active_prompt(self, project_id: str, prompt_id: str) -> bool:
        """Set a prompt as the active one for a project.

        This deactivates any previously active prompt for the project.

        Args:
            project_id: The project ID.
            prompt_id: The prompt ID to set as active.

        Returns:
            True if the update succeeded, False otherwise.
        """
        pass
