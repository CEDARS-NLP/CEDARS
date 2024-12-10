from unittest.mock import patch
import pytest
from app.adjudication_handler import SentenceHighlighter
from app.adjudication_handler import AnnotationFilterStrategy
from app.adjudication_handler import AdjudicationHandler
from app.cedars_enums import ReviewStatus

def test_highlighted_text(db):
    text_highlighter = SentenceHighlighter()
    note = db.get_all_notes("1111111111")[0]
    annotations_for_note = db.get_all_annotations_for_note(note["text_id"])
    assert "<br>" in text_highlighter.get_highlighted_text(note,
                                                           annotations_for_note)

@pytest.mark.parametrize(
    "annotations, expected_indices",
    [
        (
            [
                {"sentence": "This is a test.", "_id": 1},
                {"sentence": "This is a test.", "_id": 2},
                {"sentence": "Another test.", "_id": 3},
                {"sentence": "this is a test.", "_id": 4},  # Duplicate (case insensitive)
            ],
            [1, 3],
        ),
        (
            [
                {"sentence": "Unique sentence.", "_id": 1},
                {"sentence": "Another unique sentence.", "_id": 2},
            ],
            [],
        ),
    ],
)
def test_filter_duplicates_by_patient(annotations, expected_indices):
    strategy = AnnotationFilterStrategy()
    result = strategy._filter_duplicates_by_patient(annotations)
    assert result == expected_indices


@pytest.mark.parametrize(
    "annotations, expected_indices",
    [
        (
            [
                {"sentence": "This is a test.", "note_id": 1, "_id": 0},
                {"sentence": "Another test.", "note_id": 1, "_id": 1},
                {"sentence": "This is a test.", "note_id": 1, "_id": 2},
                {"sentence": "This is a test.", "note_id": 2, "_id": 3},
                {"sentence": "This is a test 2.", "note_id": 2, "_id": 4},
                {"sentence": "this is a test.", "note_id": 2,  "_id": 5},
            ],
            [2, 5],
        ),
        (
            [
                {"sentence": "Unique.", "note_id": 1, "_id": 1},
                {"sentence": "Also unique.", "note_id": 2, "_id": 2},
            ],
            [],
        ),
        (
            [
                {"sentence": "Unique.", "note_id": 1, "_id": 1},
                {"sentence": "Unique.", "note_id": 2, "_id": 2},
            ],
            [],
        )
    ],
)
def test_filter_duplicates_by_note(annotations, expected_indices):
    strategy = AnnotationFilterStrategy()
    result = strategy._filter_duplicates_by_note(annotations)
    assert result == expected_indices

@pytest.mark.parametrize(
    "raw_annotations, hide_duplicates, stored_event_date, stored_annotation_id, expected_patient_data, expected_duplicates",
    [
        # Case 1: Unreviewed annotations exist, hide_duplicates=True
        (
            [
                {"_id": "1", 'note_id' : 'N1', "sentence": "Test sentence 1", "reviewed": 1},
                {"_id": "2", 'note_id' : 'N1', "sentence": "Test sentence 1", "reviewed": 0},
                {"_id": "3", 'note_id' : 'N2', "sentence": "Test sentence 2", "reviewed": 0},
            ],
            True,
            None,
            None,
            {
                'event_date': None,
                'event_annotation_id': None,
                'annotation_ids': ["1", "3"],
                'review_statuses': [ReviewStatus.REVIEWED, ReviewStatus.UNREVIEWED],
                'current_index': 1,  # First unreviewed annotation
            },
            ["2"],
        ),
        # Case 2: No unreviewed annotations, stored_event_date provided
        (
            [
                {"_id": "1", 'note_id' : 'N1', "sentence": "Test sentence 1", "reviewed": 1},
                {"_id": "2", 'note_id' : 'N2', "sentence": "Test sentence 2", "reviewed": 1},
            ],
            False,
            "2024-12-01",
            "2",
            {
                'event_date': "2024-12-01",
                'event_annotation_id': "2",
                'annotation_ids': ["1", "2"],
                'review_statuses': [ReviewStatus.REVIEWED, ReviewStatus.REVIEWED],
                'current_index': 1,  # Stored annotation ID index
            },
            [],
        ),
        # Case 3: No unreviewed annotations, no stored_event_date
        (
            [
                {"_id": "1", 'note_id' : 'N1', "sentence": "Test sentence 1", "reviewed": 1},
                {"_id": "2", 'note_id' : 'N2', "sentence": "Test sentence 2", "reviewed": 1},
            ],
            True,
            None,
            None,
            {
                'event_date': None,
                'event_annotation_id': None,
                'annotation_ids': ["1", "2"],
                'review_statuses': [ReviewStatus.REVIEWED, ReviewStatus.REVIEWED],
                'current_index': 0,  # Default to index 0
            },
            [],
        ),
    ],
)
def test_init_patient_data(
    raw_annotations,
    hide_duplicates,
    stored_event_date,
    stored_annotation_id,
    expected_patient_data,
    expected_duplicates,
):
    handler = AdjudicationHandler("1111111111")
    patient_data, duplicates = handler.init_patient_data(
        raw_annotations, hide_duplicates, stored_event_date, stored_annotation_id
    )
    assert patient_data == expected_patient_data
    assert duplicates == expected_duplicates

@pytest.mark.parametrize(
    "input_patient_id, input_patient_data, expected_patient_id, expected_patient_data",
    [
        (
            "patient_2",
            {
                'event_date': "2024-12-01",
                'event_annotation_id': "2",
                'annotation_ids': ["1", "2"],
                'review_statuses': [ReviewStatus.REVIEWED, ReviewStatus.UNREVIEWED],
                'current_index': 1,
            },
            "patient_2",
            {
                'event_date': "2024-12-01",
                'event_annotation_id': "2",
                'annotation_ids': ["1", "2"],
                'review_statuses': [ReviewStatus.REVIEWED, ReviewStatus.UNREVIEWED],
                'current_index': 1,
            },
        ),
        (
            "patient_3",
            {
                'event_date': None,
                'event_annotation_id': None,
                'annotation_ids': [],
                'review_statuses': [],
                'current_index': -1,
            },
            "patient_3",
            {
                'event_date': None,
                'event_annotation_id': None,
                'annotation_ids': [],
                'review_statuses': [],
                'current_index': -1,
            },
        ),
        (
            "patient_1",
            {
                'event_date': "2024-12-05",
                'event_annotation_id': "5",
                'annotation_ids': ["3", "4", "5"],
                'review_statuses': [ReviewStatus.UNREVIEWED, ReviewStatus.REVIEWED, ReviewStatus.REVIEWED],
                'current_index': 0,
            },
            "patient_1",
            {
                'event_date': "2024-12-05",
                'event_annotation_id': "5",
                'annotation_ids': ["3", "4", "5"],
                'review_statuses': [ReviewStatus.UNREVIEWED, ReviewStatus.REVIEWED, ReviewStatus.REVIEWED],
                'current_index': 0,
            },
        ),
    ],
)
def test_load_from_patient_data(
    input_patient_id,
    input_patient_data,
    expected_patient_id,
    expected_patient_data,
):
    handler = AdjudicationHandler('input_patient_id')
    handler.load_from_patient_data(input_patient_id, input_patient_data)
    assert handler.patient_id == expected_patient_id
    assert handler.get_patient_data() == expected_patient_data