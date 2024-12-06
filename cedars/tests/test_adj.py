from unittest.mock import patch
import pytest
from app.adjudication_handler import SentenceHighlighter
from app.adjudication_handler import AnnotationFilterStrategy

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
