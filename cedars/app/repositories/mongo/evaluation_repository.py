"""MongoDB evaluation repository implementation."""

from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId

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
from app.repositories.interfaces.evaluation_repository import (
    EvaluationRepositoryInterface,
)


class MongoEvaluationRepository(EvaluationRepositoryInterface):
    """MongoDB implementation of evaluation repository."""

    # -------------------------------------------------------------------------
    # Collection Properties
    # -------------------------------------------------------------------------

    @property
    def sessions_collection(self):
        return mongo.db["EVALUATION_SESSIONS"]

    @property
    def judgments_collection(self):
        return mongo.db["EVALUATION_JUDGMENTS"]

    @property
    def prompts_collection(self):
        return mongo.db["VALIDATED_PROMPTS"]

    # -------------------------------------------------------------------------
    # Model Conversion Helpers
    # -------------------------------------------------------------------------

    def _session_to_model(self, doc: dict) -> Optional[EvaluationSession]:
        """Convert MongoDB document to EvaluationSession model."""
        if doc is None:
            return None

        doc["id"] = str(doc.pop("_id", None))

        # Convert nested objects to Pydantic models
        if "sample_config" in doc and isinstance(doc["sample_config"], dict):
            doc["sample_config"] = SampleConfig(**doc["sample_config"])

        if "llm_config" in doc and isinstance(doc["llm_config"], dict):
            doc["llm_config"] = LLMConfigModel(**doc["llm_config"])

        if "event_definition" in doc and isinstance(doc["event_definition"], dict):
            doc["event_definition"] = EventDefinitionModel(**doc["event_definition"])

        if "metrics" in doc and isinstance(doc["metrics"], dict):
            doc["metrics"] = EvaluationMetrics(**doc["metrics"])

        return EvaluationSession(**doc)

    def _judgment_to_model(self, doc: dict) -> Optional[EvaluationJudgment]:
        """Convert MongoDB document to EvaluationJudgment model."""
        if doc is None:
            return None

        doc["id"] = str(doc.pop("_id", None))

        # Convert nested LLMPrediction
        if "llm_prediction" in doc and isinstance(doc["llm_prediction"], dict):
            doc["llm_prediction"] = LLMPrediction(**doc["llm_prediction"])

        return EvaluationJudgment(**doc)

    def _prompt_to_model(self, doc: dict) -> Optional[ValidatedPrompt]:
        """Convert MongoDB document to ValidatedPrompt model."""
        if doc is None:
            return None

        doc["id"] = str(doc.pop("_id", None))

        # Convert nested objects
        if "event_definition" in doc and isinstance(doc["event_definition"], dict):
            doc["event_definition"] = EventDefinitionModel(**doc["event_definition"])

        if "llm_config" in doc and isinstance(doc["llm_config"], dict):
            doc["llm_config"] = LLMConfigModel(**doc["llm_config"])

        if "evaluation_metrics" in doc and isinstance(doc["evaluation_metrics"], dict):
            doc["evaluation_metrics"] = EvaluationMetrics(**doc["evaluation_metrics"])

        return ValidatedPrompt(**doc)

    # -------------------------------------------------------------------------
    # Evaluation Sessions
    # -------------------------------------------------------------------------

    def create_session(self, session: EvaluationSession) -> str:
        """Create a new evaluation session."""
        doc = session.model_dump(exclude={"id"}, exclude_none=True)

        # Ensure created_at is set
        if "created_at" not in doc or doc["created_at"] is None:
            doc["created_at"] = datetime.now(timezone.utc)

        result = self.sessions_collection.insert_one(doc)
        return str(result.inserted_id)

    def get_session(self, session_id: str) -> Optional[EvaluationSession]:
        """Get an evaluation session by ID."""
        try:
            doc = self.sessions_collection.find_one({"_id": ObjectId(session_id)})
            return self._session_to_model(doc)
        except Exception:
            return None

    def get_sessions_by_project(self, project_id: str) -> list[EvaluationSession]:
        """Get all evaluation sessions for a project."""
        cursor = self.sessions_collection.find(
            {"project_id": project_id}
        ).sort("created_at", -1)
        return [self._session_to_model(doc) for doc in cursor]

    def update_session_status(self, session_id: str, status: str) -> bool:
        """Update the status of an evaluation session."""
        try:
            result = self.sessions_collection.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": {"status": status}},
            )
            return result.modified_count > 0
        except Exception:
            return False

    def update_session_metrics(
        self, session_id: str, metrics: EvaluationMetrics
    ) -> bool:
        """Update the metrics for an evaluation session."""
        try:
            result = self.sessions_collection.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": {"metrics": metrics.model_dump()}},
            )
            return result.modified_count > 0
        except Exception:
            return False

    def set_sampled_notes(self, session_id: str, note_ids: list[str]) -> bool:
        """Set the sampled note IDs for an evaluation session."""
        try:
            result = self.sessions_collection.update_one(
                {"_id": ObjectId(session_id)},
                {"$set": {"sampled_note_ids": note_ids}},
            )
            return result.modified_count > 0
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # Evaluation Judgments
    # -------------------------------------------------------------------------

    def create_judgment(self, judgment: EvaluationJudgment) -> str:
        """Create a new evaluation judgment."""
        doc = judgment.model_dump(exclude={"id"}, exclude_none=True)
        result = self.judgments_collection.insert_one(doc)
        return str(result.inserted_id)

    def get_judgment(
        self, session_id: str, note_id: str
    ) -> Optional[EvaluationJudgment]:
        """Get an evaluation judgment by session and note ID."""
        doc = self.judgments_collection.find_one({
            "session_id": session_id,
            "note_id": note_id,
        })
        return self._judgment_to_model(doc)

    def get_judgments_by_session(self, session_id: str) -> list[EvaluationJudgment]:
        """Get all judgments for an evaluation session."""
        cursor = self.judgments_collection.find({"session_id": session_id})
        return [self._judgment_to_model(doc) for doc in cursor]

    def get_next_unjudged(self, session_id: str) -> Optional[EvaluationJudgment]:
        """Get the next note needing human review in a session.

        Finds judgments that haven't been reviewed yet (judged_at is null).
        """
        doc = self.judgments_collection.find_one({
            "session_id": session_id,
            "judged_at": None,
        })
        return self._judgment_to_model(doc)

    def update_judgment(
        self, session_id: str, note_id: str, judgment: str, judged_by: str
    ) -> bool:
        """Record a human judgment for an LLM prediction."""
        try:
            result = self.judgments_collection.update_one(
                {
                    "session_id": session_id,
                    "note_id": note_id,
                },
                {
                    "$set": {
                        "judgment": judgment,
                        "judged_by": judged_by,
                        "judged_at": datetime.now(timezone.utc),
                    }
                },
            )
            return result.modified_count > 0
        except Exception:
            return False

    def count_by_judgment(self, session_id: str) -> dict[str, int]:
        """Count judgments by type for a session."""
        pipeline = [
            {"$match": {"session_id": session_id}},
            {"$group": {"_id": "$judgment", "count": {"$sum": 1}}},
        ]

        result = {}
        for doc in self.judgments_collection.aggregate(pipeline):
            result[doc["_id"]] = doc["count"]

        return result

    # -------------------------------------------------------------------------
    # Validated Prompts
    # -------------------------------------------------------------------------

    def create_validated_prompt(self, prompt: ValidatedPrompt) -> str:
        """Create a new validated prompt."""
        doc = prompt.model_dump(exclude={"id"}, exclude_none=True)

        # Ensure validated_at is set
        if "validated_at" not in doc or doc["validated_at"] is None:
            doc["validated_at"] = datetime.now(timezone.utc)

        result = self.prompts_collection.insert_one(doc)
        return str(result.inserted_id)

    def get_validated_prompt(self, prompt_id: str) -> Optional[ValidatedPrompt]:
        """Get a validated prompt by ID."""
        try:
            doc = self.prompts_collection.find_one({"_id": ObjectId(prompt_id)})
            return self._prompt_to_model(doc)
        except Exception:
            return None

    def get_active_prompt(self, project_id: str) -> Optional[ValidatedPrompt]:
        """Get the active validated prompt for a project."""
        doc = self.prompts_collection.find_one({
            "project_id": project_id,
            "is_active": True,
        })
        return self._prompt_to_model(doc)

    def get_prompts_by_project(self, project_id: str) -> list[ValidatedPrompt]:
        """Get all validated prompts for a project."""
        cursor = self.prompts_collection.find(
            {"project_id": project_id}
        ).sort("validated_at", -1)
        return [self._prompt_to_model(doc) for doc in cursor]

    def set_active_prompt(self, project_id: str, prompt_id: str) -> bool:
        """Set a prompt as the active one for a project.

        This deactivates any previously active prompt for the project.
        """
        try:
            # First, deactivate all prompts for this project
            self.prompts_collection.update_many(
                {"project_id": project_id},
                {"$set": {"is_active": False}},
            )

            # Then, activate the specified prompt
            result = self.prompts_collection.update_one(
                {"_id": ObjectId(prompt_id)},
                {"$set": {"is_active": True}},
            )
            return result.modified_count > 0
        except Exception:
            return False
