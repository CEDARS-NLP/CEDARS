"""MongoDB project repository implementation."""

from datetime import datetime
from typing import Optional

from app.database import mongo
from app.models.project import ProjectInfo
from app.models.query import Query, TagQuery
from app.models.result import Result
from app.repositories.interfaces.project_repository import ProjectRepositoryInterface


class MongoProjectRepository(ProjectRepositoryInterface):
    """MongoDB implementation of project repository."""

    @property
    def info_collection(self):
        return mongo.db["INFO"]

    @property
    def query_collection(self):
        return mongo.db["QUERY"]

    @property
    def results_collection(self):
        return mongo.db["RESULTS"]

    @property
    def patients_collection(self):
        return mongo.db["PATIENTS"]

    @property
    def notes_collection(self):
        return mongo.db["NOTES"]

    @property
    def annotations_collection(self):
        return mongo.db["ANNOTATIONS"]

    # Project info operations
    def get_info(self) -> Optional[dict]:
        doc = self.info_collection.find_one()
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    def get_project_name(self) -> Optional[str]:
        doc = self.info_collection.find_one()
        return doc.get("project") if doc else None

    def get_version(self) -> Optional[str]:
        doc = self.info_collection.find_one()
        return doc.get("CEDARS_version") if doc else None

    def create_project(
        self,
        project_name: str,
        investigator_name: str,
        project_id: str,
        cedars_version: Optional[str] = None,
    ) -> bool:
        info = {
            "creation_time": datetime.now(),
            "project": project_name,
            "project_id": project_id,
            "investigator": investigator_name,
            "CEDARS_version": cedars_version,
            "pines_url": None,
            "is_pines_server_enabled": False,
        }
        result = self.info_collection.insert_one(info)
        return result.inserted_id is not None

    def update_project_name(self, new_name: str) -> bool:
        result = self.info_collection.update_one({}, {"$set": {"project": new_name}})
        return result.modified_count > 0

    # PINES configuration
    def get_pines_url(self) -> Optional[str]:
        doc = self.info_collection.find_one()
        return doc.get("pines_url") if doc else None

    def is_pines_enabled(self) -> bool:
        doc = self.info_collection.find_one()
        return doc.get("is_pines_server_enabled", False) if doc else False

    def update_pines_url(self, url: str) -> bool:
        result = self.info_collection.update_one({}, {"$set": {"pines_url": url}})
        return result.modified_count > 0

    def update_pines_status(self, enabled: bool) -> bool:
        result = self.info_collection.update_one(
            {}, {"$set": {"is_pines_server_enabled": enabled}}
        )
        return result.modified_count > 0

    def create_pines_info(self, pines_url: str, is_url_from_api: bool) -> bool:
        result = self.info_collection.update_one(
            {},
            {"$set": {"pines_url": pines_url, "is_pines_server_enabled": is_url_from_api}},
        )
        return result.modified_count > 0

    # Query operations
    def get_search_query(self, key: str = "query") -> Optional[str]:
        doc = self.query_collection.find_one({"current": True})
        return doc.get(key) if doc else None

    def get_search_query_details(self) -> Optional[Query]:
        doc = self.query_collection.find_one({"current": True})
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id", None))
        if doc.get("tag_query"):
            doc["tag_query"] = TagQuery(**doc["tag_query"])
        return Query(**doc)

    def save_query(
        self,
        query: str,
        exclude_negated: bool,
        hide_duplicates: bool,
        skip_after_event: bool,
        tag_query: dict,
        date_range: Optional[tuple],
    ) -> bool:
        # Mark existing queries as not current
        self.query_collection.update_one({"current": True}, {"$set": {"current": False}})

        info = {
            "query": query,
            "exclude_negated": exclude_negated,
            "hide_duplicates": hide_duplicates,
            "skip_after_event": skip_after_event,
            "tag_query": tag_query,
            "current": True,
        }

        if date_range:
            info["date_min"] = date_range[0]
            info["date_max"] = date_range[1]

        result = self.query_collection.insert_one(info)
        return result.inserted_id is not None

    # Results operations
    def get_results(self, patient_id: str) -> Optional[Result]:
        doc = self.results_collection.find_one({"patient_id": patient_id})
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id", None))
        return Result(**doc)

    def results_exist(self, patient_id: str) -> bool:
        doc = self.results_collection.find_one({"patient_id": patient_id})
        return doc is not None

    def upsert_results(self, patient_id: str, results: dict) -> bool:
        result = self.results_collection.update_one(
            {"patient_id": patient_id},
            {"$set": results},
            upsert=True,
        )
        return result.modified_count > 0 or result.upserted_id is not None

    def get_all_results(self, columns: Optional[list[str]] = None) -> list[dict]:
        projection = None
        if columns:
            projection = {col: 1 for col in columns}
            projection["_id"] = 0
        cursor = self.results_collection.find({}, projection).sort([("index_no", 1)])
        return list(cursor)

    # Statistics
    def get_stats(self) -> dict:
        """Get current project statistics."""
        # Unique patients
        unique_patients_pipeline = [{"$group": {"_id": "$patient_id"}}]
        unique_patients = len(list(self.notes_collection.aggregate(unique_patients_pipeline)))

        # Patients with annotations
        annotated_patients_pipeline = [
            {"$match": {"isNegated": False}},
            {"$group": {"_id": "$patient_id"}},
        ]
        annotated_patients = len(
            list(self.annotations_collection.aggregate(annotated_patients_pipeline))
        )

        # Reviewed patients
        reviewed_patients_pipeline = [
            {"$match": {"reviewed": True}},
            {"$group": {"_id": "$patient_id"}},
        ]
        reviewed_patients = len(
            list(self.patients_collection.aggregate(reviewed_patients_pipeline))
        )

        # User review counts
        user_review_pipeline = [
            {"$match": {"reviewed": True}},
            {"$group": {"_id": "$reviewed_by", "count": {"$sum": 1}}},
        ]
        user_reviews = {
            doc["_id"]: doc["count"]
            for doc in self.patients_collection.aggregate(user_review_pipeline)
        }

        # Lemma distribution
        lemma_pipeline = [
            {"$match": {"isNegated": False}},
            {"$group": {"_id": "$token", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
            {"$project": {"token": "$_id", "_id": 0, "count": 1}},
        ]
        lemma_distribution = list(self.annotations_collection.aggregate(lemma_pipeline))

        # Total annotations (non-negated)
        total_annotations = self.annotations_collection.count_documents({"isNegated": False})

        return {
            "unique_patients": unique_patients,
            "annotated_patients": annotated_patients,
            "reviewed_patients": reviewed_patients,
            "user_reviews": user_reviews,
            "lemma_distribution": lemma_distribution,
            "total_annotations": total_annotations,
        }

    # Database operations
    def create_indices(self) -> None:
        """Create database indices."""
        # Notes indices
        self.notes_collection.create_index([("text_id", 1)], unique=True)
        self.notes_collection.create_index([("patient_id", 1)])
        self.notes_collection.create_index([("patient_id", 1), ("text_id", 1)], unique=True)

        # Patients indices
        self.patients_collection.create_index([("patient_id", 1)], unique=True)

        # Results indices
        self.results_collection.create_index([("patient_id", 1)], unique=True)

        # Users indices
        mongo.db["USERS"].create_index([("user", 1)], unique=True)

        # Task indices
        mongo.db["TASK"].create_index([("job_id", 1)], unique=True)

        # Notes summary indices
        mongo.db["NOTES_SUMMARY"].create_index([("patient_id", 1)])

        # PINES indices
        mongo.db["PINES"].create_index([("text_id", 1)], unique=True)
        mongo.db["PINES"].create_index([("patient_id", 1)])

    def drop_database(self, name: str) -> bool:
        try:
            mongo.db.drop_collection(name)
            return True
        except Exception:
            return False

    def terminate_project(self) -> bool:
        """Terminate and clean up the project."""
        collections = [
            "PATIENTS",
            "NOTES",
            "ANNOTATIONS",
            "RESULTS",
            "PINES",
            "NOTES_SUMMARY",
            "TASK",
            "QUERY",
        ]
        for collection in collections:
            mongo.db.drop_collection(collection)
        return True
