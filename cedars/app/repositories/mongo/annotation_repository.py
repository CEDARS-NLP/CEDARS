"""MongoDB annotation repository implementation."""

from datetime import datetime
from typing import Optional

from bson import ObjectId

from app.database import mongo
from app.models.annotation import Annotation
from app.cedars_enums import ReviewStatus
from app.repositories.interfaces.annotation_repository import AnnotationRepositoryInterface


class MongoAnnotationRepository(AnnotationRepositoryInterface):
    """MongoDB implementation of annotation repository."""

    @property
    def collection(self):
        return mongo.db["ANNOTATIONS"]

    @property
    def notes_collection(self):
        return mongo.db["NOTES"]

    def _to_model(self, doc: dict) -> Annotation:
        """Convert MongoDB document to Annotation model."""
        if doc is None:
            return None
        doc["id"] = str(doc.pop("_id", None))
        # Handle MongoDB field name differences
        if "isNegated" in doc:
            doc["is_negated"] = doc.pop("isNegated")
        return Annotation(**doc)

    def get_by_id(self, annotation_id: str) -> Optional[Annotation]:
        doc = self.collection.find_one({"_id": ObjectId(annotation_id)})
        return self._to_model(doc) if doc else None

    def get_note_for_annotation(self, annotation_id: str) -> Optional[dict]:
        annotation = self.collection.find_one({"_id": ObjectId(annotation_id)})
        if not annotation:
            return None
        note = self.notes_collection.find_one({"text_id": annotation["note_id"]})
        return note

    def get_by_note(self, note_id: str, include_negated: bool = False) -> list[Annotation]:
        query = {"note_id": note_id}
        if not include_negated:
            query["isNegated"] = False
        cursor = self.collection.find(query).sort(
            [("text_date", 1), ("sentence_number", 1)]
        )
        return [self._to_model(doc) for doc in cursor]

    def get_by_sentence(self, note_id: str, sentence_number: int) -> list[Annotation]:
        cursor = self.collection.find(
            {"note_id": note_id, "sentence_number": sentence_number, "isNegated": False}
        ).sort([("text_date", 1), ("note_start_index", 1)])
        return [self._to_model(doc) for doc in cursor]

    def get_by_patient(self, patient_id: str, include_negated: bool = False) -> list[Annotation]:
        query = {"patient_id": patient_id}
        if not include_negated:
            query["isNegated"] = False
        cursor = self.collection.find(query).sort(
            [("text_date", 1), ("note_id", 1), ("note_start_index", 1)]
        )
        return [self._to_model(doc) for doc in cursor]

    def get_patient_annotation_ids(
        self, patient_id: str, reviewed_status: int = 0, key: str = "_id"
    ) -> list[str]:
        query = {
            "patient_id": patient_id,
            "isNegated": False,
            "reviewed": reviewed_status,
        }
        cursor = self.collection.find(query).sort(
            [("note_id", 1), ("text_date", 1), ("sentence_number", 1)]
        )
        if key == "_id":
            return [str(doc["_id"]) for doc in cursor]
        return [doc.get(key) for doc in cursor]

    def get_annotations_post_event(
        self, patient_id: str, event_date: datetime
    ) -> list[Annotation]:
        cursor = self.collection.find(
            {
                "patient_id": patient_id,
                "text_date": {"$gte": event_date},
                "reviewed": ReviewStatus.UNREVIEWED.value,
            }
        )
        return [self._to_model(doc) for doc in cursor]

    def insert_one(self, annotation: dict) -> str:
        result = self.collection.insert_one(annotation)
        return str(result.inserted_id)

    def get_all(self) -> list[Annotation]:
        cursor = self.collection.find()
        return [self._to_model(doc) for doc in cursor]

    def count(self, include_negated: bool = True) -> int:
        query = {} if include_negated else {"isNegated": False}
        return self.collection.count_documents(query)

    def mark_reviewed(self, annotation_id: str) -> bool:
        result = self.collection.update_one(
            {"_id": ObjectId(annotation_id)},
            {"$set": {"reviewed": ReviewStatus.REVIEWED.value}},
        )
        return result.modified_count > 0

    def batch_mark_reviewed(self, annotation_ids: list[str]) -> int:
        if not annotation_ids:
            return 0
        object_ids = [ObjectId(aid) for aid in annotation_ids]
        result = self.collection.update_many(
            {"_id": {"$in": object_ids}},
            {"$set": {"reviewed": ReviewStatus.REVIEWED.value}},
        )
        return result.modified_count

    def revert_reviewed(self, annotation_id: str) -> bool:
        result = self.collection.update_one(
            {"_id": ObjectId(annotation_id)},
            {"$set": {"reviewed": ReviewStatus.UNREVIEWED.value}},
        )
        return result.modified_count > 0

    def mark_skipped_post_event(self, patient_id: str, event_date: datetime) -> int:
        result = self.collection.update_many(
            {
                "patient_id": patient_id,
                "text_date": {"$gte": event_date},
                "reviewed": ReviewStatus.UNREVIEWED.value,
            },
            {"$set": {"reviewed": ReviewStatus.SKIPPED.value}},
        )
        return result.modified_count

    def revert_skipped(self, patient_id: str) -> int:
        result = self.collection.update_many(
            {"patient_id": patient_id, "reviewed": ReviewStatus.SKIPPED.value},
            {"$set": {"reviewed": ReviewStatus.UNREVIEWED.value}},
        )
        return result.modified_count

    def update_note_review_status(self, annotation_id: str, reviewed_by: str) -> dict:
        """Check if all annotations for a note are reviewed and update note status."""
        annotation = self.collection.find_one({"_id": ObjectId(annotation_id)})
        if not annotation:
            return {"note_reviewed": False, "patient_reviewed": False}

        note_id = annotation["note_id"]
        patient_id = annotation["patient_id"]

        # Check if any unreviewed annotations remain for this note
        unreviewed_count = self.collection.count_documents(
            {"note_id": note_id, "reviewed": ReviewStatus.UNREVIEWED.value}
        )

        note_reviewed = unreviewed_count == 0
        if note_reviewed:
            self.notes_collection.update_one(
                {"text_id": note_id},
                {"$set": {"reviewed": True, "reviewed_by": reviewed_by}},
            )

        return {
            "note_reviewed": note_reviewed,
            "patient_reviewed": False,  # Determined by caller
            "note_id": note_id,
            "patient_id": patient_id,
        }

    def batch_update_note_review_status(
        self, annotation_ids: list[str], reviewed_by: str
    ) -> dict:
        """Batch check and update note review status."""
        if not annotation_ids:
            return {"notes_reviewed": [], "patient_reviewed": False}

        # Get unique note_ids from the annotations
        object_ids = [ObjectId(aid) for aid in annotation_ids]
        annotations = list(self.collection.find({"_id": {"$in": object_ids}}))

        note_ids = list(set(a["note_id"] for a in annotations))

        # For each note, check if all annotations are reviewed
        reviewed_notes = []
        for note_id in note_ids:
            unreviewed_count = self.collection.count_documents(
                {"note_id": note_id, "reviewed": ReviewStatus.UNREVIEWED.value}
            )
            if unreviewed_count == 0:
                reviewed_notes.append(note_id)

        # Update reviewed notes
        if reviewed_notes:
            self.notes_collection.update_many(
                {"text_id": {"$in": reviewed_notes}},
                {"$set": {"reviewed": True, "reviewed_by": reviewed_by}},
            )

        return {"notes_reviewed": reviewed_notes, "patient_reviewed": False}

    def mark_all_in_note_reviewed(self, note_id: str) -> int:
        result = self.collection.update_many(
            {"note_id": note_id},
            {"$set": {"reviewed": ReviewStatus.REVIEWED.value}},
        )
        return result.modified_count

    def delete_all(self) -> int:
        result = self.collection.delete_many({})
        return result.deleted_count

    def create_indices(self) -> None:
        """Create database indices for annotations."""
        indices = [
            [("patient_id", 1), ("note_id", 1)],
            [("patient_id", 1), ("isNegated", 1), ("text_date", 1), ("note_id", 1), ("note_start_index", 1)],
            [("patient_id", 1), ("text_date", 1), ("reviewed", 1)],
            [("note_id", 1), ("reviewed", 1)],
            [("patient_id", 1), ("reviewed", 1)],
            [("note_id", 1), ("isNegated", 1), ("text_date", 1), ("sentence_number", 1)],
            [("note_id", 1), ("isNegated", 1), ("text_date", 1), ("sentence_number", 1), ("note_start_index", 1)],
            [("patient_id", 1), ("isNegated", 1), ("reviewed", 1), ("sentence_number", 1), ("note_id", 1), ("text_date", 1)],
            [("patient_id", 1), ("reviewed", 1), ("text_date", 1)],
            [("patient_id", 1), ("note_start_index", 1), ("note_id", 1), ("text_date", 1)],
        ]

        for index in indices:
            self.collection.create_index(index)
