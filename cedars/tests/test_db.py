# Test for db.py

import pytest


@pytest.mark.parametrize("expected_result, patient_id", [
    [103, None],
    [12, 1111111111]])
def test_get_documents_to_annotate(db, expected_result, patient_id):
    # Act (call the function)
    result = len(list(db.get_documents_to_annotate(patient_id)))

    # Assert (verify the result)
    assert result == expected_result


def test_add_user(db):
    # Arrange (set up the data)
    username = "test1"
    password = "test1"
    is_admin = False

    # Act (call the function)
    db.add_user(username, password, is_admin)

    # Assert (verify the result)
    assert db.get_user(username) is not None


def test_save_query(db):
    tag_query = {
        "exact": False,
        "nlp_apply": False,
        "include": None,
        "exclude": None
    }

    exclude_negated = True
    hide_duplicates = False
    skip_after_event = True

    query = "DVT OR (!deep AND vein AND thromb*) OR clot OR embol*"

    db.save_query(query=query,
                  tag_query=tag_query,
                  exclude_negated=exclude_negated,
                  hide_duplicates=hide_duplicates,
                  skip_after_event=skip_after_event)

    assert db.get_search_query(query_key="hide_duplicates") == hide_duplicates
    assert db.get_search_query(query_key="exclude_negated") == exclude_negated
    assert db.get_search_query(query_key="skip_after_event") == skip_after_event
    assert db.get_search_query(query_key="query") == query
    assert db.get_search_query(query_key="tag_query") == tag_query

    # same query should return False
    assert db.save_query(query=query,
                         tag_query=tag_query,
                         exclude_negated=exclude_negated,
                         hide_duplicates=hide_duplicates,
                         skip_after_event=skip_after_event) is False


def test_get_info(db):
    assert db.get_info() is not None


@pytest.mark.parametrize("note_id, expected_result", [["UNIQUE0000000001", 1]])
def test_get_all_annotations_for_note(db, note_id, expected_result):
    from app.nlpprocessor import NlpProcessor
    nlp_processor = NlpProcessor()
    assert len(db.get_all_annotations_for_note(note_id)) == 0
    nlp_processor.process_notes(1111111111)
    assert len(db.get_all_annotations_for_note(note_id)) == expected_result
    assert len(list(db.get_documents_to_annotate())) == 91
    assert len(list(db.get_documents_to_annotate(1111111111))) == 0


@pytest.mark.parametrize("note_id", ["UNIQUE0000000001"])
def test_get_annotation(db, note_id):
    annot = db.get_all_annotations_for_note(note_id)[0]
    annot_id = annot["_id"]
    res = db.get_annotation(annot_id)
    assert res["token"] == "embolism"
    assert res["start_index"] == 252
    assert res["end_index"] == 260
    assert res['note_start_index'] == 252
