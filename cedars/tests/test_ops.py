import pytest
from flask import request
from unittest.mock import patch
from app.ops import (
    allowed_data_file,
    highlighted_text
)


def test_allowed_data_file():
    assert allowed_data_file("file.csv") is True
    assert allowed_data_file("file.xlsx") is True
    assert allowed_data_file("file.json") is True
    assert allowed_data_file("file.parquet") is True
    assert allowed_data_file("file.pickle") is True
    assert allowed_data_file("file.pkl") is True
    assert allowed_data_file("file.xml") is True
    assert allowed_data_file("file.txt") is False


@pytest.mark.parametrize("project_name, project_id", [
    ("Test Project", None),
    ("Updated Project", 1)
])
def test_project_details_post(client, db, project_name, project_id):
    data = {"project_name": project_name,
            "project_id": project_id,
            "update_project_name": 1}
    with patch.object(request, 'form') as mock_form:
        mock_form.return_value = data
        response = client.post("/ops/project_details")

    assert response.status_code == 200
    # if project_id:
    #     assert db.get_info()["project"] == project_name
    # else:
    #     assert db.get_info()["project"] == project_name


def test_project_details_post_terminate(client, db):
    with patch.object(request, 'form') as mock_form:
        mock_form.return_value.terminate = True
        mock_form.return_value.terminate_conf = "DELETE EVERYTHIG"
        response = client.post("/ops/project_details")
    assert response.status_code == 200
    # assert db.get_info() == {}


# def test_load_pandas_dataframe():
#     with patch.object(Minio("localhost:9000"),
#                       'get_object') as mock_minio:
#         mock_minio.return_value = BytesIO(b"col1,col2\n1,2\n3,4")
#         df = load_pandas_dataframe("test.csv")

#         assert isinstance(df, pd.DataFrame)
#         assert df.shape == (2, 2)
#         assert list(df.columns) == ["col1", "col2"]


# def test_emr_to_mongodb(db):
#     with patch("app.ops.load_pandas_dataframe") as mocked_dataframe:
#         mocked_dataframe.return_value = pd.DataFrame({"patient_id": [11, 11, 22, 22],
#                                                       "text_date": ['2022-10-22',
#                                                                     '2022-10-22',
#                                                                     '2022-10-21',
#                                                                     '2022-10-22'],
#                                                       "text": ["note1", "note2", "note3", "note4"]})

#         EMR_to_mongodb("dummy_path")

#         assert db.get_total_counts("NOTES") == 4
#         assert db.get_total_counts("PATIENTS") == 2
#     mocked_dataframe.return_value = pd.DataFrame({"patient_id": [1, 1, 2, 2],
#                                                   "text": ["note1", "note2", "note3", "note4"]})

#     EMR_to_mongodb("dummy_path")

#     assert db.get_total_counts("NOTES") == 4
#     assert db.get_total_counts("PATIENTS") == 2


def test_upload_data_get(client):
    response = client.get("/ops/upload_data")
    assert response.status_code == 200


# def test_upload_data_post_no_file(client, db):
#     data = {"data_file": (BytesIO(b"abcdef"), "")}
#     with patch.object(request, 'files') as mock_files:
#         mock_files.return_value = data
#         response = client.post("/ops/upload_data")
#         assert response.status_code == 302


# def test_upload_data_post_invalid_file(client, db):
#     data = {"data_file": (BytesIO(b"abcdef"), "test.txt")}
#     with patch.object(request, 'files') as mock_files:
#         mock_files.return_value = data
#         response = client.post("/ops/upload_data", content_type='multipart/form-data')
#         assert response.status_code == 302
#         assert db.get_total_counts("NOTES") == 96


# def test_upload_data_post_valid_file(client, db):
#     data = {"data_file": (BytesIO(b"abcdef"), "test.csv")}
#     with patch.object(request, 'files') as mock_files:
#         mock_files.return_value = data
#         response = client.post("/ops/upload_data", content_type='multipart/form-data')
#         assert response.status_code == 302


def test_upload_query_get(client, db):
    response = client.get("/ops/upload_query")
    assert response.status_code == 200


# def test_upload_query_post_invalid(client, db):
#     data = {"regex_query": "())"}
#     response = client.post("/ops/upload_query", data=data)
#     assert response.status_code == 200
#     assert b"Invalid query" in response.data


def test_upload_query_post_valid(client, db):
    data = {"regex_query": "test", "nlp_apply": True, "keep_duplicates": False, "skip_after_event": True}
    response = client.post("/ops/upload_query", data=data)
    assert response.status_code == 200
    # mocked_nlp_processing.assert_called_once()
    assert db.get_total_counts("ANNOTATIONS") == 0
    assert db.get_total_counts("PATIENTS", reviewed=False) == 4


def test_do_nlp_processing(client):
    response = client.get("/ops/start_process")
    assert response.status_code == 302


def test_get_job_status(client, db):
    response = client.get("/ops/job_status")
    assert response.status_code == 200


# def test_save_adjudications_update_date(client, db):
#     nlp = nlpprocessor.NlpProcessor()
#     nlp.process_notes(patient_id=1111111111)
#     annotation = db.get_all_annotations()[0]
#     session["annotations"] = [str(annotation["_id"])]
#     session["index"] = 0
#     data = {"date_entry": "2020-01-01", "submit_button": "new_date"}
#     response = client.post("/ops/save_adjudications", data=data)
#     assert response.status_code == 302
#     assert db.get_annotation_date(str(annotation["_id"])) == datetime(2020, 1, 1)


# def test_save_adjudications_delete_date(client, db):
#     annotation = db.get_all_annotations()[0]
#     session["annotations"] = [str(annotation["_id"])]
#     session["index"] = 0
#     data = {"submit_button": "del_date"}
#     response = client.post("/ops/save_adjudications", data=data)
#     assert response.status_code == 302
#     assert db.get_annotation_date(str(annotation["_id"])) is None


# def test_save_adjudications_add_comment(client, db):
#     annotation = db.get_all_annotations()[0]
#     session["annotations"] = [str(annotation["_id"])]
#     session["index"] = 0
#     session["patient_id"] = annotation["patient_id"]
#     data = {"comment": "test comment", "submit_button": "comment"}
#     response = client.post("/ops/save_adjudications", data=data)
#     assert response.status_code == 302
#     assert db.get_patient_by_id(annotation["patient_id"])["comments"] == ["test comment"]


# def test_save_adjudications_prev_next(client, db):
#     annotations = db.get_all_annotations()
#     session["annotations"] = [str(a["_id"]) for a in annotations]
#     session["index"] = 1
#     session["total_count"] = len(annotations)

#     data = {"submit_button": "prev"}
#     response = client.post("/ops/save_adjudications", data=data)
#     assert response.status_code == 302
#     assert session["index"] == 0

#     data = {"submit_button": "next"}
#     response = client.post("/ops/save_adjudications", data=data)
#     assert response.status_code == 302
#     assert session["index"] == 1


# def test_save_adjudications_reviewed(client, db):
#     annotation = db.get_all_annotations()[0]
#     session["annotations"] = [str(annotation["_id"])]
#     session["index"] = 0
#     session["patient_id"] = annotation["patient_id"]
#     session["unreviewed_annotations_index"] = [1]
#     data = {"submit_button": "adjudicate"}
#     response = client.post("/ops/save_adjudications", data=data)
#     assert response.status_code == 302
#     assert db.get_annotation(str(annotation["_id"]))["reviewed"] is True
#     assert db.get_patient_lock_status(annotation["patient_id"]) is False
#     assert "patient_id" not in session


# def test_show_annotation(client, db):
#     annotation = db.get_all_annotations()[0]
#     session["annotations"] = [str(annotation["_id"])]
#     session["index"] = 0
#     session["total_count"] = 1
#     session["patient_id"] = annotation["patient_id"]
#     response = client.get("/ops/show_annotation")
#     assert response.status_code == 200
#     assert b"test</mark>" in response.data


# def test_adjudicate_records_get(client, db):
#     response = client.get("/ops/adjudicate_records")
#     assert response.status_code == 302
#     assert session["patient_id"] == 1111111111


# def test_adjudicate_records_post_search(client, db):
#     data = {"patient_id": "1111111111"}
#     response = client.post("/ops/adjudicate_records", data=data)
#     assert response.status_code == 302
#     assert session["patient_id"] == 1111111111


# def test_adjudicate_records_post_no_patient(client, db):
#     data = {"patient_id": "1111111111"}
#     response = client.post("/ops/adjudicate_records", data=data)
#     assert response.status_code == 302
#     assert session["patient_id"] == 1111111111


def test_highlighted_text(db):
    note = db.get_all_notes(1111111111)[0]
    assert "<br>" in highlighted_text(note)


# def test_download_annotations(client, db, mocker):
#     mocked_get_object = mocker.patch("app.database.minio.get_object")
#     mocked_get_object.return_value = BytesIO(b"test,test\n1,2")
#     response = client.get("/ops/download_annotations")
#     assert response.status_code == 200
#     assert response.data == b"test,test\n1,2"
