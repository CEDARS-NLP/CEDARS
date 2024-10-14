'''
Automated tests for db.py
'''

from datetime import datetime
import pytest

@pytest.mark.parametrize("expected_result, patient_id", [
    [103, None],
    [12, "1111111111"]])
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
    nlp_processor.process_notes("1111111111")
    assert len(db.get_all_annotations_for_note(note_id)) == expected_result
    assert len(list(db.get_documents_to_annotate())) == 91
    assert len(list(db.get_documents_to_annotate("1111111111"))) == 0


@pytest.mark.parametrize("note_id", ["UNIQUE0000000001"])
def test_get_annotation(db, note_id):
    annot = db.get_all_annotations_for_note(note_id)[0]
    annot_id = annot["_id"]
    res = db.get_annotation(annot_id)
    assert res["token"] == "embolism"
    assert res['note_start_index'] == 252


def test_get_annotation_note(db):
    note_id = "UNIQUE0000000001"
    annot = db.get_all_annotations_for_note(note_id)[0]
    annot_id = annot["_id"]
    note = db.get_annotation_note(annot_id)
    assert note["text_id"] == note_id


def test_get_patient_by_id(db):
    patient = db.get_patient_by_id("1111111111")
    assert patient is not None
    assert patient["patient_id"] == "1111111111"


def test_get_patient(db):
    patient_id = db.get_patient()
    assert patient_id == "5555555555"


def test_get_patients_to_annotate(db):
    patient_id = db.get_patients_to_annotate()
    assert patient_id == "1111111111"


def test_get_all_annotations_for_patient(db):
    result = db.get_all_annotations_for_patient("1111111111")
    assert len(result) == 3


def test_get_all_annotations_for_patient_paged(db):
    result = db.get_all_annotations_for_patient_paged("1111111111", page=1, page_size=1)
    assert result["total"] == 3
    assert len(result["annotations"]) == 1


def test_get_patient_annotation_ids(db):
    result = db.get_patient_annotation_ids("1111111111")
    assert len(result) == 3


def test_get_event_date(db):
    assert db.get_event_date("1111111111") is None


def test_get_first_note_date_for_patient(db):
    date = datetime(2009, 12, 25, 0, 0)
    assert db.get_first_note_date_for_patient("1111111111") == date


def test_get_last_note_date_for_patient(db):
    date = datetime(2010, 1, 15, 0, 0)
    assert db.get_last_note_date_for_patient("1111111111") == date


def test_get_all_annotations(db):
    assert len(db.get_all_annotations()) == 3


def test_get_proj_name(db):
    assert db.get_proj_name() is not None


def test_get_curr_version(db):
    assert db.get_curr_version() == "test_version"


def test_get_project_users(db):
    assert len(db.get_project_users()) == 2
    assert "test1" in db.get_project_users()


def test_get_all_patients(db):
    assert len(db.get_all_patients()) == 5


def test_get_patient_ids(db):
    assert len(db.get_patient_ids()) == 5
    assert "1111111111" in db.get_patient_ids()


def test_get_patient_lock_status(db):
    assert db.get_patient_lock_status("1111111111") is False


def test_get_all_notes(db):
    assert len(db.get_all_notes("1111111111")) == 12


def test_get_patient_notes(db):
    assert len(list(db.get_patient_notes("1111111111"))) == 3
    assert len(list(db.get_patient_notes("1111111111", reviewed=True))) == 9


def test_get_total_counts(db):
    assert db.get_total_counts("ANNOTATIONS") == 3
    assert db.get_total_counts("PATIENTS") == 5


def test_get_annotated_notes_for_patient(db):
    assert db.get_annotated_notes_for_patient("1111111111")[0] == "UNIQUE0000000011"


def test_mark_annotation_reviewed(db):
    note_id = "UNIQUE0000000001"
    annot = db.get_all_annotations_for_note(note_id)[0]
    annot_id = str(annot["_id"])
    db.mark_annotation_reviewed(annot_id)
    assert db.get_annotation(annot_id)["reviewed"] is True


def test_update_event_date(db):
    note_id = "UNIQUE0000000001"
    annot = db.get_all_annotations_for_note(note_id)[0]
    patient_id = annot["patient_id"]
    anno_id = annot["_id"]
    db.update_event_date(patient_id, "2020-01-01", anno_id)
    assert db.get_event_date(patient_id) == datetime(2020, 1, 1)


def test_delete_event_date(db):
    note_id = "UNIQUE0000000001"
    annot = db.get_all_annotations_for_note(note_id)[0]
    patient_id = annot["patient_id"]
    db.delete_event_date(patient_id)
    assert db.get_event_date(patient_id) is None

def test_get_event_annotation_id(db):
    patient_id = "1111111111"
    event_anno_id = db.get_event_annotation_id(patient_id)
    # Event annotation should be none by default
    assert event_anno_id is None

def test_update_event_annotation_id(db):
    patient_id = "1111111111"
    note_id = "UNIQUE0000000001"
    annot = db.get_all_annotations_for_note(note_id)[0]
    anno_id = annot["_id"]
    db.update_event_annotation_id(patient_id, anno_id)
    event_anno_id = db.get_event_annotation_id(patient_id)
    assert anno_id == event_anno_id

def test_delete_event_annotation_id(db):
    patient_id = "1111111111"
    db.delete_event_annotation_id(patient_id)
    event_anno_id = db.get_event_annotation_id(patient_id)
    assert event_anno_id is None

def test_mark_patient_reviewed(db):
    db.mark_patient_reviewed("1111111111", "test1")
    patient = db.get_patient_by_id("1111111111")
    assert patient["reviewed"] is True
    assert patient["reviewed_by"] == "test1"

def test_get_patient_reviewer(db):
    patient_id = "1111111111"
    reviewer = db.get_patient_reviewer(patient_id)
    assert reviewer == "test1"


def test_mark_note_reviewed(db):
    db.mark_note_reviewed("UNIQUE0000000001", "test1")
    note = list(db.get_patient_notes("1111111111", reviewed=True))[0]
    assert note["reviewed"] is True
    assert note["reviewed_by"] == "test1"


def test_add_comment(db):
    note_id = "UNIQUE0000000001"
    annot = db.get_all_annotations_for_note(note_id)[0]
    annot_id = str(annot["_id"])
    db.add_comment(annot_id, "test comment")
    patient = db.get_patient_by_id("1111111111")
    assert patient["comments"] == "test comment"

def test_delete_comment(db):
    note_id = "UNIQUE0000000001"
    annot = db.get_all_annotations_for_note(note_id)[0]
    annot_id = str(annot["_id"])
    db.add_comment(annot_id, "")
    patient = db.get_patient_by_id("1111111111")
    assert patient["comments"] == ""

def test_set_patient_lock_status(db):
    db.set_patient_lock_status("1111111111", True)
    assert db.get_patient_lock_status("1111111111") is True
    db.set_patient_lock_status("1111111111", False)
    assert db.get_patient_lock_status("1111111111") is False


def test_remove_all_locked(db):
    db.set_patient_lock_status("1111111111", True)
    db.remove_all_locked()
    assert db.get_patient_lock_status("1111111111") is False


def test_empty_annotations(db):
    db.empty_annotations()
    assert db.get_total_counts("ANNOTATIONS") == 0


def test_is_admin_user(db):
    assert db.is_admin_user("test1") is False


def test_get_curr_stats(db):
    stats = db.get_curr_stats()
    assert stats["number_of_patients"] == 5
    assert stats["number_of_annotated_patients"] == 0
    assert stats["number_of_reviewed"] == 1
