"""SQLite project repository implementation."""

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import func

from app.models.project import ProjectInfo
from app.models.query import Query, TagQuery
from app.models.result import Result
from app.repositories.interfaces.project_repository import ProjectRepositoryInterface
from .database import session_scope, engine
from .tables import (
    ProjectInfoTable,
    QueryTable,
    ResultTable,
    PatientTable,
    NoteTable,
    AnnotationTable,
    NotesSummaryTable,
    TaskTable,
    PredictionTable,
    Base,
)


class SQLiteProjectRepository(ProjectRepositoryInterface):
    """SQLite implementation of project repository."""

    # Project info operations
    def get_info(self) -> Optional[dict]:
        with session_scope() as session:
            row = session.query(ProjectInfoTable).first()
            if not row:
                return None
            return {
                "_id": str(row.id),
                "creation_time": row.creation_time,
                "project": row.project,
                "project_id": row.project_id,
                "investigator": row.investigator,
                "CEDARS_version": row.cedars_version,
                "pines_url": row.pines_url,
                "is_pines_server_enabled": row.is_pines_server_enabled,
            }

    def get_project_name(self) -> Optional[str]:
        with session_scope() as session:
            row = session.query(ProjectInfoTable).first()
            return row.project if row else None

    def get_version(self) -> Optional[str]:
        with session_scope() as session:
            row = session.query(ProjectInfoTable).first()
            return row.cedars_version if row else None

    def create_project(
        self,
        project_name: str,
        investigator_name: str,
        project_id: str,
        cedars_version: Optional[str] = None,
    ) -> bool:
        with session_scope() as session:
            info = ProjectInfoTable(
                creation_time=datetime.now(),
                project=project_name,
                project_id=project_id,
                investigator=investigator_name,
                cedars_version=cedars_version,
                pines_url=None,
                is_pines_server_enabled=False,
            )
            session.add(info)
            return True

    def update_project_name(self, new_name: str) -> bool:
        with session_scope() as session:
            rows_updated = session.query(ProjectInfoTable).update({"project": new_name})
            return rows_updated > 0

    # PINES configuration
    def get_pines_url(self) -> Optional[str]:
        with session_scope() as session:
            row = session.query(ProjectInfoTable).first()
            return row.pines_url if row else None

    def is_pines_enabled(self) -> bool:
        with session_scope() as session:
            row = session.query(ProjectInfoTable).first()
            return row.is_pines_server_enabled if row else False

    def update_pines_url(self, url: str) -> bool:
        with session_scope() as session:
            rows_updated = session.query(ProjectInfoTable).update({"pines_url": url})
            return rows_updated > 0

    def update_pines_status(self, enabled: bool) -> bool:
        with session_scope() as session:
            rows_updated = session.query(ProjectInfoTable).update(
                {"is_pines_server_enabled": enabled}
            )
            return rows_updated > 0

    def create_pines_info(self, pines_url: str, is_url_from_api: bool) -> bool:
        with session_scope() as session:
            rows_updated = session.query(ProjectInfoTable).update(
                {"pines_url": pines_url, "is_pines_server_enabled": is_url_from_api}
            )
            return rows_updated > 0

    # Query operations
    def get_search_query(self, key: str = "query") -> Optional[str]:
        with session_scope() as session:
            row = session.query(QueryTable).filter_by(current=True).first()
            if not row:
                return None
            if key == "query":
                return row.query
            return getattr(row, key, None)

    def get_search_query_details(self) -> Optional[Query]:
        with session_scope() as session:
            row = session.query(QueryTable).filter_by(current=True).first()
            if not row:
                return None

            tag_query = None
            if row.tag_query_json:
                tag_data = json.loads(row.tag_query_json)
                tag_query = TagQuery(**tag_data)

            return Query(
                id=str(row.id),
                query=row.query,
                exclude_negated=row.exclude_negated,
                hide_duplicates=row.hide_duplicates,
                skip_after_event=row.skip_after_event,
                tag_query=tag_query,
                date_min=row.date_min,
                date_max=row.date_max,
                current=row.current,
            )

    def save_query(
        self,
        query: str,
        exclude_negated: bool,
        hide_duplicates: bool,
        skip_after_event: bool,
        tag_query: dict,
        date_range: Optional[tuple],
    ) -> bool:
        with session_scope() as session:
            # Mark existing queries as not current
            session.query(QueryTable).filter_by(current=True).update({"current": False})

            q = QueryTable(
                query=query,
                exclude_negated=exclude_negated,
                hide_duplicates=hide_duplicates,
                skip_after_event=skip_after_event,
                tag_query_json=json.dumps(tag_query) if tag_query else None,
                current=True,
            )

            if date_range:
                q.date_min = date_range[0]
                q.date_max = date_range[1]

            session.add(q)
            return True

    # Results operations
    def get_results(self, patient_id: str) -> Optional[Result]:
        with session_scope() as session:
            row = session.query(ResultTable).filter_by(patient_id=patient_id).first()
            if not row:
                return None
            return Result(
                id=str(row.id),
                patient_id=row.patient_id,
                total_notes=row.total_notes,
                reviewed_notes=row.reviewed_notes,
                total_sentences=row.total_sentences or "",
                reviewed_sentences=row.reviewed_sentences,
                sentences=row.sentences or "",
                event_date=row.event_date,
                event_information=row.event_information or "",
                first_note_date=row.first_note_date,
                last_note_date=row.last_note_date,
                comments=row.comments or "",
                reviewer=row.reviewer,
                max_score_note_id=row.max_score_note_id,
                max_score_note_date=row.max_score_note_date,
                max_score=row.max_score,
                predicted_notes=row.predicted_notes or "",
                last_updated=row.last_updated,
                index_no=row.index_no,
            )

    def results_exist(self, patient_id: str) -> bool:
        with session_scope() as session:
            row = session.query(ResultTable).filter_by(patient_id=patient_id).first()
            return row is not None

    def upsert_results(self, patient_id: str, results: dict) -> bool:
        with session_scope() as session:
            existing = session.query(ResultTable).filter_by(patient_id=patient_id).first()
            if existing:
                for key, value in results.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
            else:
                result_row = ResultTable(patient_id=patient_id, **results)
                session.add(result_row)
            return True

    def get_all_results(self, columns: Optional[list[str]] = None) -> list[dict]:
        with session_scope() as session:
            rows = session.query(ResultTable).order_by(ResultTable.index_no).all()
            results = []
            for row in rows:
                if columns:
                    result = {col: getattr(row, col, None) for col in columns}
                else:
                    result = {
                        "patient_id": row.patient_id,
                        "total_notes": row.total_notes,
                        "reviewed_notes": row.reviewed_notes,
                        "event_date": row.event_date,
                        "comments": row.comments,
                        "reviewer": row.reviewer,
                        "index_no": row.index_no,
                    }
                results.append(result)
            return results

    # Statistics
    def get_stats(self) -> dict:
        """Get current project statistics."""
        with session_scope() as session:
            # Unique patients
            unique_patients = session.query(func.count(func.distinct(NoteTable.patient_id))).scalar()

            # Patients with annotations
            annotated_patients = (
                session.query(func.count(func.distinct(AnnotationTable.patient_id)))
                .filter_by(is_negated=False)
                .scalar()
            )

            # Reviewed patients
            reviewed_patients = (
                session.query(func.count(PatientTable.id))
                .filter_by(reviewed=True)
                .scalar()
            )

            # User review counts
            user_reviews_query = (
                session.query(PatientTable.reviewed_by, func.count(PatientTable.id))
                .filter_by(reviewed=True)
                .group_by(PatientTable.reviewed_by)
                .all()
            )
            user_reviews = {row[0]: row[1] for row in user_reviews_query if row[0]}

            # Lemma distribution (top 10 tokens)
            lemma_query = (
                session.query(AnnotationTable.token, func.count(AnnotationTable.id).label("count"))
                .filter_by(is_negated=False)
                .group_by(AnnotationTable.token)
                .order_by(func.count(AnnotationTable.id).desc())
                .limit(10)
                .all()
            )
            lemma_distribution = [{"token": row[0], "count": row[1]} for row in lemma_query]

            # Total annotations (non-negated)
            total_annotations = (
                session.query(func.count(AnnotationTable.id))
                .filter_by(is_negated=False)
                .scalar()
            )

            return {
                "unique_patients": unique_patients or 0,
                "annotated_patients": annotated_patients or 0,
                "reviewed_patients": reviewed_patients or 0,
                "user_reviews": user_reviews,
                "lemma_distribution": lemma_distribution,
                "total_annotations": total_annotations or 0,
            }

    # Database operations
    def create_indices(self) -> None:
        """Create database indices (handled by SQLAlchemy table definitions)."""
        Base.metadata.create_all(bind=engine)

    def drop_database(self, name: str) -> bool:
        """Drop a table by name."""
        table_map = {
            "PATIENTS": PatientTable,
            "NOTES": NoteTable,
            "ANNOTATIONS": AnnotationTable,
            "RESULTS": ResultTable,
            "PINES": PredictionTable,
            "NOTES_SUMMARY": NotesSummaryTable,
            "TASK": TaskTable,
            "QUERY": QueryTable,
        }
        if name in table_map:
            with session_scope() as session:
                session.query(table_map[name]).delete()
            return True
        return False

    def terminate_project(self) -> bool:
        """Terminate and clean up the project."""
        tables = [
            PatientTable,
            NoteTable,
            AnnotationTable,
            ResultTable,
            PredictionTable,
            NotesSummaryTable,
            TaskTable,
            QueryTable,
        ]
        with session_scope() as session:
            for table in tables:
                session.query(table).delete()
        return True
