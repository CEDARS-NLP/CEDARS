"""Patients workspace API tests."""
from datetime import date

from tests_fastapi import sql_test_helpers as sql


GOOD_PASSWORD = "Abcdef12!!"


def _project(client, username: str, name: str) -> str:
    client.post("/api/v1/auth/register", json={
        "username": username, "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False,
    })
    client.post("/api/v1/auth/login", json={"username": username, "password": GOOD_PASSWORD})
    return client.post("/api/v1/projects", json={"name": name}).json()["id"]


def test_patient_list_search_filter_and_project_isolation(client):
    first_project = _project(client, "FirstAdmin", "First")
    sql.seed_patient(first_project, "ABC-1", index_no=0, reviewed=True)
    sql.seed_patient(first_project, "DEF-2", index_no=1, reviewed=False)
    sql.seed_note(first_project, "N1", "ABC-1", "note", date(2024, 1, 1))
    sql.seed_annotation(first_project, "N1", "ABC-1", date(2024, 1, 1), "event", "event", 0)

    response = client.get(f"/api/v1/projects/{first_project}/data/patients?search=abc")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["status"] == "reviewed"
    assert response.json()["items"][0]["note_count"] == 1

    response = client.get(f"/api/v1/projects/{first_project}/data/patients?status=new")
    assert response.status_code == 200, response.text
    assert [item["patient_id_ext"] for item in response.json()["items"]] == ["DEF-2"]

    second_project = _project(client, "SecondAdmin", "Second")
    assert client.get(f"/api/v1/projects/{first_project}/data/patients").status_code == 403
    assert client.get(f"/api/v1/projects/{second_project}/data/patients").json()["total"] == 0