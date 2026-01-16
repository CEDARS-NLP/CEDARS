"""MongoDB note repository implementation."""

from datetime import datetime
from typing import Optional

from pymongo import UpdateOne

from app.database import mongo
from app.models.note import Note
from app.models.notes_summary import NotesSummary
from app.repositories.interfaces.note_repository import NoteRepositoryInterface


class MongoNoteRepository(NoteRepositoryInterface):
    """MongoDB implementation of note repository."""

    @property
    def collection(self):
        return mongo.db["NOTES"]

    @property
    def summary_collection(self):
        return mongo.db["NOTES_SUMMARY"]

    def _to_model(self, doc: dict) -> Note:
        """Convert MongoDB document to Note model."""
        if doc is None:
            return None
        doc["id"] = str(doc.pop("_id", None))
        return Note(**doc)

    def _to_summary_model(self, doc: dict) -> NotesSummary:
        """Convert MongoDB document to NotesSummary model."""
        if doc is None:
            return None
        doc["id"] = str(doc.pop("_id", None))
        return NotesSummary(**doc)

    def get_by_id(self, text_id: str) -> Optional[Note]:
        doc = self.collection.find_one({"text_id": text_id})
        return self._to_model(doc) if doc else None

    def get_by_patient(self, patient_id: str) -> list[Note]:
        cursor = self.collection.find({"patient_id": patient_id})
        return [self._to_model(doc) for doc in cursor]

    def get_patient_notes_for_review(self, patient_id: str, reviewed: bool = False) -> list[Note]:
        query = {"patient_id": patient_id}
        if reviewed is not None:
            query["reviewed"] = reviewed
        cursor = self.collection.find(query)
        return [self._to_model(doc) for doc in cursor]

    def get_note_date(self, text_id: str) -> Optional[datetime]:
        doc = self.collection.find_one({"text_id": text_id})
        return doc.get("text_date") if doc else None

    def count_by_patient(self, patient_id: str, reviewed: Optional[bool] = None) -> int:
        query = {"patient_id": patient_id}
        if reviewed is not None:
            query["reviewed"] = reviewed
        return self.collection.count_documents(query)

    def count(self, **filters) -> int:
        return self.collection.count_documents(filters)

    def bulk_insert(self, notes: list[dict]) -> int:
        if not notes:
            return 0
        result = self.collection.insert_many(notes)
        return len(result.inserted_ids)

    def mark_reviewed(self, text_id: str, reviewed_by: str) -> bool:
        result = self.collection.update_one(
            {"text_id": text_id},
            {"$set": {"reviewed": True, "reviewed_by": reviewed_by}},
        )
        return result.modified_count > 0

    def batch_mark_reviewed(self, text_ids: list[str], reviewed_by: str) -> int:
        if not text_ids:
            return 0
        result = self.collection.update_many(
            {"text_id": {"$in": text_ids}},
            {"$set": {"reviewed": True, "reviewed_by": reviewed_by}},
        )
        return result.modified_count

    def revert_reviewed(self, text_id: str, reviewed_by: str) -> bool:
        result = self.collection.update_one(
            {"text_id": text_id},
            {"$set": {"reviewed": False, "reviewed_by": reviewed_by}},
        )
        return result.modified_count > 0

    def reset_all_reviewed(self) -> int:
        result = self.collection.update_many(
            {},
            {"$set": {"reviewed": False, "reviewed_by": ""}},
        )
        return result.modified_count

    def get_documents_to_annotate(self, patient_id: Optional[str] = None) -> list[Note]:
        """Get notes that have no annotations and are not reviewed."""
        pipeline = [
            {
                "$lookup": {
                    "from": "ANNOTATIONS",
                    "localField": "text_id",
                    "foreignField": "note_id",
                    "as": "annotations",
                }
            },
            {"$match": {"annotations": {"$eq": []}, "reviewed": {"$ne": True}}},
        ]

        if patient_id:
            pipeline.insert(0, {"$match": {"patient_id": patient_id}})

        cursor = self.collection.aggregate(pipeline)
        return [self._to_model(doc) for doc in cursor]

    def update_notes_summary(self) -> int:
        """Update/rebuild the notes summary cache."""
        pipeline = [
            {
                "$group": {
                    "_id": "$patient_id",
                    "num_notes": {"$sum": 1},
                    "first_note_date": {"$min": "$text_date"},
                    "last_note_date": {"$max": "$text_date"},
                }
            },
            {
                "$project": {
                    "patient_id": "$_id",
                    "num_notes": 1,
                    "first_note_date": 1,
                    "last_note_date": 1,
                    "_id": 0,
                }
            },
        ]

        summaries = list(self.collection.aggregate(pipeline))

        if not summaries:
            return 0

        operations = [
            UpdateOne(
                {"patient_id": s["patient_id"]},
                {"$setOnInsert": s},
                upsert=True,
            )
            for s in summaries
        ]

        self.summary_collection.bulk_write(operations, ordered=False)
        return len(summaries)

    def get_notes_summary(self) -> list[NotesSummary]:
        cursor = self.summary_collection.find()
        return [self._to_summary_model(doc) for doc in cursor]

    def get_first_note_date(self, patient_id: str) -> Optional[datetime]:
        doc = self.summary_collection.find_one(
            {"patient_id": patient_id},
            {"_id": 0, "first_note_date": 1},
        )
        return doc.get("first_note_date") if doc else None

    def get_last_note_date(self, patient_id: str) -> Optional[datetime]:
        doc = self.summary_collection.find_one(
            {"patient_id": patient_id},
            {"_id": 0, "last_note_date": 1},
        )
        return doc.get("last_note_date") if doc else None

    def get_num_notes(self, patient_id: str) -> int:
        doc = self.summary_collection.find_one(
            {"patient_id": patient_id},
            {"_id": 0, "num_notes": 1},
        )
        return doc.get("num_notes", 0) if doc else 0
