"""Tests for audit log models and service."""

from app.audit.models import AuditAction, AuditEntry
from app.audit.service import log_action, get_patient_activity, query_audit_log


class TestAuditModels:
    def test_audit_action_values(self):
        assert AuditAction.ANNOTATION_REVIEWED.value == "annotation_reviewed"
        assert AuditAction.PATIENT_LOCKED.value == "patient_locked"
        assert AuditAction.DATA_INGESTED.value == "data_ingested"
        assert AuditAction.DATA_PURGED.value == "data_purged"
        assert AuditAction.DATA_RESYNCED.value == "data_resynced"

    def test_audit_entry_defaults(self):
        entry = AuditEntry(
            project_id="proj1",
            action=AuditAction.ANNOTATION_REVIEWED,
            user_id="user1",
        )
        assert entry.patient_id is None
        assert entry.detail == {}

    def test_audit_entry_with_detail(self):
        entry = AuditEntry(
            project_id="proj1",
            action=AuditAction.EVENT_DATE_SET,
            user_id="user1",
            patient_id="pat1",
            detail={"annotation_id": "ann1", "event_date": "2024-01-15"},
        )
        assert entry.patient_id == "pat1"
        assert entry.detail["annotation_id"] == "ann1"


class TestAuditService:
    def test_log_action_importable(self):
        assert callable(log_action)

    def test_get_patient_activity_importable(self):
        assert callable(get_patient_activity)

    def test_query_audit_log_importable(self):
        assert callable(query_audit_log)
