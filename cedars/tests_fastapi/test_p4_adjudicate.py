"""P4 tests: the adjudication workflow (seeded notes/annotations, no NLP run)."""
from datetime import datetime

import pytest
from bson import ObjectId

from app import database

GOOD_PASSWORD = "Abcdef12!!"
#            0123456789012345678901234567890123456789
NOTE_TEXT = "Patient has cancer. No embolism found."
#   "cancer"  -> [12, 18)   "embolism" -> [23, 31)


def _proj_db(pid):
    return database.get_client()[database.project_db_name(pid)]


def _seed_patient(pid, patient="1"):
    db_ = _proj_db(pid)
    note_date = datetime(2024, 1, 1)
    db_["PATIENTS"].insert_one({
        "patient_id": patient, "reviewed": False, "locked": False, "index_no": 0,
        "event_date": None, "event_annotation_id": None, "comments": ""})
    db_["NOTES"].insert_one({
        "text_id": "N1", "patient_id": patient, "text": NOTE_TEXT,
        "text_date": note_date, "reviewed": False, "text_tag_1": "oncology"})
    db_["ANNOTATIONS"].insert_many([
        {"_id": ObjectId(), "patient_id": patient, "note_id": "N1",
         "sentence": "Patient has cancer.", "note_start_index": 12, "note_end_index": 18,
         "sentence_number": 0, "isNegated": False, "reviewed": 0,
         "text_date": note_date, "token": "cancer"},
        {"_id": ObjectId(), "patient_id": patient, "note_id": "N1",
         "sentence": "No embolism found.", "note_start_index": 23, "note_end_index": 31,
         "sentence_number": 1, "isNegated": False, "reviewed": 0,
         "text_date": note_date, "token": "embolism"},
    ])


@pytest.fixture()
def reviewer(client):
    client.post("/api/v1/auth/register", json={
        "username": "AdminUser", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False})
    client.post("/api/v1/auth/login",
                json={"username": "AdminUser", "password": GOOD_PASSWORD})
    pid = client.post("/api/v1/projects", json={"name": "Cohort"}).json()["id"]
    return client, pid


def test_next_returns_first_annotation_with_offsets(reviewer):
    client, pid = reviewer
    _seed_patient(pid)

    resp = client.get(f"/api/v1/projects/{pid}/adjudicate/next")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["complete"] is False
    assert body["patient_id"] == "1"

    ann = body["annotation"]
    assert ann["pos_start"] == 1 and ann["total_pos"] == 2
    assert ann["sentence"] == "Patient has cancer."
    assert ann["full_note"] == NOTE_TEXT
    assert ann["tags"][0] == "oncology"
    # Sentence-relative offsets for the matched token.
    assert ann["sentence_evidence"] == [
        {"text": "cancer", "start_pos": 12, "end_pos": 18, "match_source": "cancer"}]
    # Absolute offsets across the whole note (both matches).
    assert [(s["text"], s["start_pos"], s["end_pos"]) for s in ann["full_note_evidence"]] == [
        ("cancer", 12, 18), ("embolism", 23, 31)]

    # Patient is now locked.
    assert _proj_db(pid)["PATIENTS"].find_one({"patient_id": "1"})["locked"] is True


def test_adjudicate_advances_then_completes(reviewer):
    client, pid = reviewer
    _seed_patient(pid)
    client.get(f"/api/v1/projects/{pid}/adjudicate/next")

    step = client.post(f"/api/v1/projects/{pid}/adjudicate/save",
                       json={"action": "adjudicate"}).json()
    assert step["annotation"]["pos_start"] == 2
    assert step["annotation"]["sentence"] == "No embolism found."

    done = client.post(f"/api/v1/projects/{pid}/adjudicate/save",
                       json={"action": "adjudicate"}).json()
    assert done["complete"] is True
    assert done["patient_complete"] is True
    # Patient marked reviewed.
    assert _proj_db(pid)["PATIENTS"].find_one({"patient_id": "1"})["reviewed"] is True


def test_navigation_shift(reviewer):
    client, pid = reviewer
    _seed_patient(pid)
    client.get(f"/api/v1/projects/{pid}/adjudicate/next")

    nxt = client.post(f"/api/v1/projects/{pid}/adjudicate/save",
                      json={"action": "next_1"}).json()
    assert nxt["annotation"]["pos_start"] == 2
    prev = client.post(f"/api/v1/projects/{pid}/adjudicate/save",
                       json={"action": "prev_1"}).json()
    assert prev["annotation"]["pos_start"] == 1


def test_new_date_sets_event_date(reviewer):
    client, pid = reviewer
    _seed_patient(pid)
    client.get(f"/api/v1/projects/{pid}/adjudicate/next")

    resp = client.post(f"/api/v1/projects/{pid}/adjudicate/save",
                       json={"action": "new_date", "event_date": "2024-01-15",
                             "comment": "found event"}).json()
    # After entering a date the current annotation carries the event date.
    assert resp["annotation"]["event_date"] == "2024-01-15"


def test_search_patient(reviewer):
    client, pid = reviewer
    _seed_patient(pid)
    resp = client.post(f"/api/v1/projects/{pid}/adjudicate/search",
                       json={"patient_id": "1"}).json()
    assert resp["patient_id"] == "1"

    missing = client.post(f"/api/v1/projects/{pid}/adjudicate/search",
                          json={"patient_id": "999"}).json()
    assert "does not exist" in (missing.get("message") or "")


def test_unlock_releases_patient(reviewer):
    client, pid = reviewer
    _seed_patient(pid)
    client.get(f"/api/v1/projects/{pid}/adjudicate/next")
    assert _proj_db(pid)["PATIENTS"].find_one({"patient_id": "1"})["locked"] is True

    resp = client.post(f"/api/v1/projects/{pid}/adjudicate/unlock")
    assert resp.status_code == 200
    assert "Unlocking patient" in resp.json()["message"]
    assert _proj_db(pid)["PATIENTS"].find_one({"patient_id": "1"})["locked"] is False


def test_no_patients_returns_complete(reviewer):
    client, pid = reviewer
    resp = client.get(f"/api/v1/projects/{pid}/adjudicate/next").json()
    assert resp["complete"] is True
