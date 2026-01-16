"""MongoDB patient repository implementation."""

from datetime import datetime
from typing import Optional

from bson import ObjectId
from pymongo import UpdateOne

from app.database import mongo
from app.models.patient import Patient
from app.repositories.interfaces.patient_repository import PatientRepositoryInterface


class MongoPatientRepository(PatientRepositoryInterface):
    """MongoDB implementation of patient repository."""

    @property
    def collection(self):
        return mongo.db["PATIENTS"]

    def _to_model(self, doc: dict) -> Patient:
        """Convert MongoDB document to Patient model."""
        if doc is None:
            return None
        doc["id"] = str(doc.pop("_id", None))
        # Handle MongoDB field name differences
        if "isNegated" in doc:
            doc["is_negated"] = doc.pop("isNegated")
        return Patient(**doc)

    def get_by_id(self, patient_id: str) -> Optional[Patient]:
        doc = self.collection.find_one({"patient_id": patient_id})
        return self._to_model(doc) if doc else None

    def get_next_unreviewed(self) -> Optional[Patient]:
        doc = self.collection.find(
            {"reviewed": False, "locked": False}
        ).sort([("index_no", 1)]).limit(1)
        docs = list(doc)
        return self._to_model(docs[0]) if docs else None

    def get_all_ids(self, reviewed_only: bool = False) -> list[str]:
        query = {} if not reviewed_only else {"reviewed": True}
        cursor = self.collection.find(query, {"patient_id": 1}).sort([("index_no", 1)])
        return [doc["patient_id"] for doc in cursor]

    def get_unreviewed_ids(self) -> list[str]:
        cursor = self.collection.find(
            {"reviewed": False, "locked": False}
        ).sort([("index_no", 1)])
        return [doc["patient_id"] for doc in cursor]

    def count(self) -> int:
        return self.collection.count_documents({})

    def bulk_upsert(self, patient_ids: set[str], start_index: int = 0) -> int:
        """Bulk insert/update patients."""
        existing_count = self.count()

        operations = []
        for i, p_id in enumerate(patient_ids):
            patient_info = {
                "patient_id": p_id,
                "reviewed": False,
                "locked": False,
                "updated": False,
                "comments": "",
                "reviewed_by": None,
                "event_annotation_id": None,
                "event_date": None,
                "admin_locked": False,
                "index_no": existing_count + start_index + i,
            }
            operations.append(
                UpdateOne(
                    {"patient_id": p_id},
                    {"$setOnInsert": patient_info},
                    upsert=True,
                )
            )

        if operations:
            # Process in chunks
            chunk_size = 1000
            for i in range(0, len(operations), chunk_size):
                chunk = operations[i : i + chunk_size]
                self.collection.bulk_write(chunk, ordered=False)

        new_count = self.count()
        return new_count - existing_count

    def mark_reviewed(self, patient_id: str, reviewed_by: str, is_reviewed: bool = True) -> bool:
        result = self.collection.update_one(
            {"patient_id": patient_id},
            {"$set": {"reviewed": is_reviewed, "reviewed_by": reviewed_by}},
        )
        return result.modified_count > 0

    def set_lock_status(self, patient_id: str, locked: bool) -> bool:
        result = self.collection.update_one(
            {"patient_id": patient_id},
            {"$set": {"locked": locked}},
        )
        return result.modified_count > 0

    def remove_all_locks(self) -> int:
        result = self.collection.update_many({}, {"$set": {"locked": False}})
        return result.modified_count

    def set_event_date(self, patient_id: str, event_date: Optional[datetime]) -> bool:
        result = self.collection.update_one(
            {"patient_id": patient_id},
            {"$set": {"event_date": event_date}},
        )
        return result.modified_count > 0

    def set_event_annotation_id(self, patient_id: str, annotation_id: Optional[str]) -> bool:
        result = self.collection.update_one(
            {"patient_id": patient_id},
            {"$set": {"event_annotation_id": annotation_id}},
        )
        return result.modified_count > 0

    def add_comment(self, patient_id: str, comment: str) -> bool:
        result = self.collection.update_one(
            {"patient_id": patient_id},
            {"$set": {"comments": comment}},
        )
        return result.modified_count > 0

    def get_reviewer(self, patient_id: str) -> Optional[str]:
        doc = self.collection.find_one({"patient_id": patient_id})
        return doc.get("reviewed_by") if doc else None

    def reset_all_reviewed(self) -> int:
        result = self.collection.update_many(
            {},
            {
                "$set": {
                    "reviewed": False,
                    "reviewed_by": "",
                    "event_annotation_id": None,
                    "event_date": None,
                    "comments": "",
                }
            },
        )
        return result.modified_count
