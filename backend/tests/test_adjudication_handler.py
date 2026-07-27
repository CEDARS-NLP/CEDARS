"""Unit tests for the ported AdjudicationHandler (faithful to cedars/app).

These are pure in-memory tests of the adjudication state machine — no DB — so
they directly verify the ported logic matches v1's behaviour.
"""

from datetime import datetime

from app.annotations.adjudication_handler import (
    AdjudicationHandler,
    AnnotationFilterStrategy,
    PatientStatus,
    ReviewStatus,
)


def _ann(_id, note_id, sentence, sent_no, start, reviewed=0, negated=False, date=None):
    return {
        "_id": _id,
        "note_id": note_id,
        "patient_id": "P1",
        "sentence": sentence,
        "sentence_number": sent_no,
        "sentence_start": start,
        "sentence_end": start + len(sentence),
        "note_start_index": start,
        "isNegated": negated,
        "text_date": date or datetime(2026, 1, 1),
        "reviewed": reviewed,
        "tokens": [
            {"token": "x", "note_start_index": start, "note_end_index": start + 1, "isNegated": negated}
        ],
    }


def test_init_selects_first_unreviewed():
    anns = [
        _ann("a1", "n1", "alpha sentence", 0, 0),
        _ann("a2", "n1", "beta sentence", 1, 20),
        _ann("a3", "n2", "gamma sentence", 0, 0),
    ]
    handler = AdjudicationHandler("P1")
    patient_data, dupes = handler.init_patient_data(anns, hide_duplicates=True)

    assert patient_data["annotation_ids"] == ["a1", "a2", "a3"]
    assert patient_data["review_statuses"] == [ReviewStatus.UNREVIEWED] * 3
    assert patient_data["current_index"] == 0
    assert dupes == []


def test_hide_duplicates_by_patient_removes_repeated_sentence():
    anns = [
        _ann("a1", "n1", "same sentence", 0, 0),
        _ann("a2", "n2", "same sentence", 0, 0),  # duplicate text across notes
        _ann("a3", "n2", "unique sentence", 1, 20),
    ]
    handler = AdjudicationHandler("P1")
    patient_data, dupes = handler.init_patient_data(anns, hide_duplicates=True)

    assert dupes == ["a2"]
    assert patient_data["annotation_ids"] == ["a1", "a3"]


def test_filter_by_note_keeps_cross_note_duplicates():
    anns = [
        _ann("a1", "n1", "same sentence", 0, 0),
        _ann("a2", "n2", "same sentence", 0, 0),  # different note → kept
    ]
    strat = AnnotationFilterStrategy()
    filtered, dupes = strat.filter_annotations(anns, hide_duplicates=False)
    assert dupes == []
    assert filtered["annotation_ids"] == ["a1", "a2"]


def test_adjudicate_advances_to_next_unreviewed():
    anns = [
        _ann("a1", "n1", "one", 0, 0),
        _ann("a2", "n1", "two", 1, 10),
    ]
    handler = AdjudicationHandler("P1")
    handler.init_patient_data(anns, hide_duplicates=True)

    handler._adjudicate_annotation()
    assert handler.patient_data["review_statuses"][0] == ReviewStatus.REVIEWED
    assert handler.patient_data["current_index"] == 1
    assert handler.is_patient_reviewed() is False

    handler._adjudicate_annotation()
    assert handler.is_patient_reviewed() is True
    assert handler.get_patient_status() == PatientStatus.REVIEWED_NO_EVENT


def test_perform_shift_navigation():
    anns = [_ann(f"a{i}", "n1", f"s{i}", i, i * 10) for i in range(5)]
    handler = AdjudicationHandler("P1")
    handler.init_patient_data(anns, hide_duplicates=True)

    handler.perform_shift("next_1")
    assert handler.patient_data["current_index"] == 1
    handler.perform_shift("next_10")
    assert handler.patient_data["current_index"] == 4  # clamped to last
    handler.perform_shift("first_anno")
    assert handler.patient_data["current_index"] == 0
    handler.perform_shift("prev_1")
    assert handler.patient_data["current_index"] == 0  # clamped to first
    handler.perform_shift("last_anno")
    assert handler.patient_data["current_index"] == 4


def test_mark_event_date_skips_later_annotations():
    d1, d2, d3 = datetime(2026, 1, 1), datetime(2026, 1, 2), datetime(2026, 1, 3)
    anns = [
        _ann("a1", "n1", "first", 0, 0, date=d1),
        _ann("a2", "n1", "second", 1, 10, date=d2),
        _ann("a3", "n1", "third", 2, 20, date=d3),
    ]
    handler = AdjudicationHandler("P1")
    handler.init_patient_data(anns, hide_duplicates=True)

    # Event on/after d2 skips a2 and a3 (both unreviewed), and reviews current a1.
    handler.mark_event_date(d2, "a1", ["a2", "a3"])

    assert handler.patient_data["review_statuses"] == [
        ReviewStatus.REVIEWED,
        ReviewStatus.SKIPPED,
        ReviewStatus.SKIPPED,
    ]
    assert handler.patient_data["event_date"] == d2.date()
    assert handler.is_patient_reviewed() is True
    assert handler.get_patient_status() == PatientStatus.REVIEWED_WITH_EVENT


def test_delete_event_date_reverts_skips():
    d1, d2 = datetime(2026, 1, 1), datetime(2026, 1, 2)
    anns = [
        _ann("a1", "n1", "first", 0, 0, date=d1),
        _ann("a2", "n1", "second", 1, 10, date=d2),
    ]
    handler = AdjudicationHandler("P1")
    handler.init_patient_data(anns, hide_duplicates=True)
    handler.mark_event_date(d2, "a1", ["a2"])
    assert ReviewStatus.SKIPPED in handler.patient_data["review_statuses"]

    handler.delete_event_date()
    assert handler.patient_data["event_date"] is None
    assert ReviewStatus.SKIPPED not in handler.patient_data["review_statuses"]
    assert handler.patient_data["review_statuses"][0] == ReviewStatus.UNREVIEWED
    assert handler.get_patient_status() == PatientStatus.UNDER_REVIEW


def test_no_annotations_status():
    handler = AdjudicationHandler("P1")
    handler.init_patient_data([], hide_duplicates=True)
    assert handler.get_patient_status() == PatientStatus.NO_ANNOTATIONS
