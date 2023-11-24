import os
import datetime
import pytest
import pandas as pd
from dotenv import dotenv_values
import sqlalchemy
from pathlib import Path

os.environ["RUN MODE"] = "Testing" # Deployment / Testing
config = dotenv_values(".env")


from app import db
from app.database import db_session, db_engine, Base
from app.sqlalchemy_tables import INFO, PATIENTS, NOTES, QUERY
from app.sqlalchemy_tables import ANNOTATIONS, COMMENTS, USERS

inspector = sqlalchemy.inspect(db_engine)


# Drop all tables from database
if sqlalchemy.inspect(db_engine).has_table("INFO"):
    INFO.__table__.drop(db_engine)

if sqlalchemy.inspect(db_engine).has_table("PATIENTS"):
    PATIENTS.__table__.drop(db_engine)

if sqlalchemy.inspect(db_engine).has_table("NOTES"):
    NOTES.__table__.drop(db_engine)

if sqlalchemy.inspect(db_engine).has_table("QUERY"):
    QUERY.__table__.drop(db_engine)

if sqlalchemy.inspect(db_engine).has_table("ANNOTATIONS"):
    ANNOTATIONS.__table__.drop(db_engine)

if sqlalchemy.inspect(db_engine).has_table("COMMENTS"):
    COMMENTS.__table__.drop(db_engine)

if sqlalchemy.inspect(db_engine).has_table("USERS"):
    USERS.__table__.drop(db_engine)

test_data = pd.read_csv(Path(__file__).parent / "simulated_patients.csv")

dummy_proj_info = {'cedars_version': 'version_2',
                    'project_name': 'proj_name',
                    'investigator_name': 'investigator_name'}


@pytest.mark.app
@pytest.mark.parametrize("obj, dictionary",
                         [(INFO(project_name = "p_n",
                                investigator_name = "i_n",
                                cedars_version = "p_v",
                                creation_time = None),
                                {'project_name' : "p_n",
                                    'investigator_name' : 'i_n',
                                    'cedars_version' : 'p_v',
                                    'creation_time' : None}),
                          
                          (USERS(user = 'Jhon',
                                 password = 'pass',
                                 is_admin = False,
                                 date_created = None),
                                {'user' : 'Jhon',
                                    'password' : 'pass',
                                    'is_admin' : False,
                                    'date_created' : None}),

                          (COMMENTS(comm_id = 1,
                                      anno_id = 2,
                                      comment = "C1"),
                                    {'comm_id' : 1,
                                        'anno_id' : 2,
                                        'comment' : 'C1'})])
def test_row_to_dict(obj, dictionary):
    new_dict = db.row_to_dict(obj)

    for key in dictionary:
        assert dictionary[key] == new_dict[key]



@pytest.mark.app
def test_create_project():
    db.create_project(dummy_proj_info['project_name'],
                      dummy_proj_info['investigator_name'],
                      dummy_proj_info['cedars_version'])
    
    retrieved_data = db.get_info()

    for key in dummy_proj_info:
        assert key in retrieved_data
        assert retrieved_data[key] == dummy_proj_info[key]
    
    assert 'creation_time' in retrieved_data
    assert type(retrieved_data['creation_time']) == type(datetime.datetime.now())

    assert db.get_proj_name() == dummy_proj_info['project_name']
    assert db.get_curr_version() == dummy_proj_info['cedars_version']


@pytest.mark.app
def test_info_creation():
    columns = inspector.get_columns('INFO')

    expected_schema = {'project_name' : {'type' : 'VARCHAR', 'nullable': False, 'default': None, 'primary_key': 1},
                       'investigator_name' : {'type': 'VARCHAR', 'nullable': True, 'default': None, 'primary_key': 0},
                       'cedars_version' : {'type': 'VARCHAR', 'nullable': True, 'default': None, 'primary_key': 0},
                       'creation_time' : {'type': 'DATETIME', 'nullable': True, 'default': None, 'primary_key': 0}}

    for col in columns:
        expected_col_info = expected_schema[col['name']]

        for attrbute in expected_col_info:
            assert str(expected_col_info[attrbute]) == str(col[attrbute])

@pytest.mark.app
def test_patients_creation():
    columns = inspector.get_columns('PATIENTS')

    expected_schema = {'patient_id' : {'type': 'INTEGER', 'nullable': False, 'default': None, 'primary_key': 1},
                       'reviewed' : {'type': 'BOOLEAN', 'nullable': True, 'default': None, 'primary_key': 0},
                       'locked' : {'type': 'BOOLEAN', 'nullable': True, 'default': None, 'primary_key': 0},
                       'updated' : {'type': 'BOOLEAN', 'nullable': True, 'default': None, 'primary_key': 0},
                       'admin_locked' : {'type': 'BOOLEAN', 'nullable': True, 'default': None, 'primary_key': 0}}

    for col in columns:
        expected_col_info = expected_schema[col['name']]

        for attrbute in expected_col_info:
            assert str(expected_col_info[attrbute]) == str(col[attrbute])

@pytest.mark.app
def test_notes_creation():
    columns = inspector.get_columns('NOTES')

    expected_schema = {'text_id' : {'type': 'VARCHAR', 'nullable': False, 'default': None, 'primary_key': 1},
                       'text' : {'type': 'TEXT', 'nullable': True, 'default': None, 'primary_key': 0},
                       'patient_id' : {'type': 'INTEGER', 'nullable': True, 'default': None, 'primary_key': 0},
                       'text_date' : {'type': 'DATETIME', 'nullable': True, 'default': None, 'primary_key': 0},
                       'doc_id' : {'type': 'VARCHAR', 'nullable': True, 'default': None, 'primary_key': 0},
                       'text_sequence' : {'type': 'INTEGER', 'nullable': True, 'default': None, 'primary_key': 0},
                       'text_tag_1' : {'type': 'VARCHAR', 'nullable': True, 'default': None, 'primary_key': 0},
                       'text_tag_2' : {'type': 'VARCHAR', 'nullable': True, 'default': None, 'primary_key': 0},
                       'text_tag_3' : {'type': 'VARCHAR', 'nullable': True, 'default': None, 'primary_key': 0},
                       'text_tag_4' : {'type': 'VARCHAR', 'nullable': True, 'default': None, 'primary_key': 0}}

    foreign_keys = {'patient_id' : (NOTES.patient_id, ['PATIENTS.patient_id'])}

    for col in columns:
        expected_col_info = expected_schema[col['name']]

        for attrbute in expected_col_info:
            assert str(expected_col_info[attrbute]) == str(col[attrbute])

        if col['name'] in foreign_keys:
            column = foreign_keys[col['name']][0]
            expected_relations = foreign_keys[col['name']][1]

            col_relations = [key.target_fullname for key in column.foreign_keys]

            assert len(expected_relations) == len(col_relations)
            for relation in expected_relations:
                assert relation in col_relations

@pytest.mark.app
def test_annotations_creation():
    columns = inspector.get_columns('ANNOTATIONS')

    expected_schema = {'anno_id' : {'type': 'INTEGER', 'nullable': False, 'default': None, 'primary_key': 1},
                       'note_id' : {'type': 'INTEGER', 'nullable': True, 'default': None, 'primary_key': 0},
                       'sentence' : {'type': 'TEXT', 'nullable': True, 'default': None, 'primary_key': 0},
                       'token' : {'type': 'VARCHAR', 'nullable': True, 'default': None, 'primary_key': 0},
                       'lemma' : {'type': 'VARCHAR', 'nullable': True, 'default': None, 'primary_key': 0},
                       'isNegated' : {'type': 'BOOLEAN', 'nullable': True, 'default': None, 'primary_key': 0},
                       'start_index' : {'type': 'INTEGER', 'nullable': True, 'default': None, 'primary_key': 0},
                       'end_index' : {'type': 'INTEGER', 'nullable': True, 'default': None, 'primary_key': 0},
                       'note_start_index' : {'type': 'INTEGER', 'nullable': True, 'default': None, 'primary_key': 0},
                       'note_end_index' : {'type': 'INTEGER', 'nullable': True, 'default': None, 'primary_key': 0},
                       'sentence_number' : {'type': 'INTEGER', 'nullable': True, 'default': None, 'primary_key': 0},
                       'patient_id' : {'type': 'INTEGER', 'nullable': True, 'default': None, 'primary_key': 0},
                       'event_date' : {'type': 'DATETIME', 'nullable': True, 'default': None, 'primary_key': 0},
                       'reviewed' : {'type': 'BOOLEAN', 'nullable': True, 'default': None, 'primary_key': 0}}

    foreign_keys = {'note_id' : (ANNOTATIONS.note_id, ['NOTES.text_id']),
                    'patient_id' : (ANNOTATIONS.patient_id, ['PATIENTS.patient_id'])}

    assert ANNOTATIONS.anno_id.autoincrement

    for col in columns:
        expected_col_info = expected_schema[col['name']]

        for attrbute in expected_col_info:
            assert str(expected_col_info[attrbute]) == str(col[attrbute])

        if col['name'] in foreign_keys:
            column = foreign_keys[col['name']][0]
            expected_relations = foreign_keys[col['name']][1]

            col_relations = [key.target_fullname for key in column.foreign_keys]

            assert len(expected_relations) == len(col_relations)
            for relation in expected_relations:
                assert relation in col_relations


@pytest.mark.app
def test_comments_creation():
    columns = inspector.get_columns('COMMENTS')

    expected_schema = {'comm_id' : {'type': 'INTEGER', 'nullable': False, 'default': None, 'primary_key': 1},
                       'anno_id' : {'type': 'INTEGER', 'nullable': True, 'default': None, 'primary_key': 0},
                       'comment' : {'type': 'TEXT', 'nullable': True, 'default': None, 'primary_key': 0}}

    foreign_keys = {'anno_id' : (COMMENTS.anno_id, ['ANNOTATIONS.anno_id'])}

    assert COMMENTS.comm_id.autoincrement

    for col in columns:
        expected_col_info = expected_schema[col['name']]

        for attrbute in expected_col_info:
            assert str(expected_col_info[attrbute]) == str(col[attrbute])

        if col['name'] in foreign_keys:
            column = foreign_keys[col['name']][0]
            expected_relations = foreign_keys[col['name']][1]

            col_relations = [key.target_fullname for key in column.foreign_keys]

            assert len(expected_relations) == len(col_relations)
            for relation in expected_relations:
                assert relation in col_relations

@pytest.mark.app
def test_users_creation():
    columns = inspector.get_columns('USERS')

    expected_schema = {'_id' : {'type': 'INTEGER', 'nullable': False, 'default': None, 'primary_key': 1},
                       'user' : {'type': 'VARCHAR', 'nullable': True, 'default': None, 'primary_key': 0},
                       'password' : {'type': 'VARCHAR', 'nullable': True, 'default': None, 'primary_key': 0},
                       'is_admin' : {'type': 'BOOLEAN', 'nullable': True, 'default': None, 'primary_key': 0},
                       'date_created' : {'type': 'DATETIME', 'nullable': True, 'default': None, 'primary_key': 0}}

    assert USERS._id.autoincrement
    assert USERS.user.unique

    for col in columns:
        expected_col_info = expected_schema[col['name']]

        for attrbute in expected_col_info:
            assert str(expected_col_info[attrbute]) == str(col[attrbute])

@pytest.mark.app
def test_query_creation():
    columns = inspector.get_columns('QUERY')

    expected_schema = {'_id' : {'type': 'INTEGER', 'nullable': False, 'default': None, 'primary_key': 1},
                       'query' : {'type': 'VARCHAR', 'nullable': True, 'default': None, 'primary_key': 0},
                       'tag_query_include' : {'type': 'VARCHAR', 'nullable': True, 'default': None, 'primary_key': 0},
                       'tag_query_exclude' : {'type': 'VARCHAR', 'nullable': True, 'default': None, 'primary_key': 0},
                       'exclude_negated' : {'type': 'BOOLEAN', 'nullable': True, 'default': None, 'primary_key': 0},
                       'hide_duplicates' : {'type': 'BOOLEAN', 'nullable': True, 'default': None, 'primary_key': 0},
                       'skip_after_event' : {'type': 'BOOLEAN', 'nullable': True, 'default': None, 'primary_key': 0},
                       'tag_query_exact' : {'type': 'BOOLEAN', 'nullable': True, 'default': None, 'primary_key': 0},
                       'tag_query_nlp_apply' : {'type': 'BOOLEAN', 'nullable': True, 'default': None, 'primary_key': 0},
                       'current' : {'type': 'BOOLEAN', 'nullable': True, 'default': None, 'primary_key': 0},
                       'date_min' : {'type': 'DATETIME', 'nullable': True, 'default': None, 'primary_key': 0},
                       'date_max' : {'type': 'DATETIME', 'nullable': True, 'default': None, 'primary_key': 0}}

    assert QUERY._id.autoincrement

    for col in columns:
        expected_col_info = expected_schema[col['name']]

        for attrbute in expected_col_info:
            assert str(expected_col_info[attrbute]) == str(col[attrbute])


@pytest.mark.app
@pytest.mark.parametrize("new_name", [("Adam"), ("Kevin")])
def test_update_project_name(new_name):
    db.update_project_name(new_name)
    assert db.get_proj_name() == new_name
    

@pytest.mark.app
@pytest.mark.parametrize("user, password, is_admin", [("Jhon", "password", False), ("Annie", "aks&And%09", True)])
def test_user_interface(user, password, is_admin):
    db.add_project_user(user, password, is_admin = is_admin)

    assert db.check_password(user, password) is True
    assert db.check_password(user, password + "123") is False

    user_info = db.get_user(user)

    assert user_info['user'] == user
    assert user_info['is_admin'] == is_admin

    assert db.is_admin_user(user) == is_admin

    usernames = db.get_project_users()
    assert user in usernames

    for name in usernames:
        assert type(name) == type("")

@pytest.mark.app
@pytest.mark.parametrize("""query, exclude_negated, hide_duplicates,
                         skip_after_event, tag_query""",
                        [("Q1", False, False, False, {'include' : [False],
                                                      'exclude' : [False],
                                                      'exact' : [False],
                                                      'nlp_apply' : [False]}),
                         ("Q2", True, True, True, {'include' : [True],
                                                      'exclude' : [True],
                                                      'exact' : [True],
                                                      'nlp_apply' : [True]})])
def test_save_and_load_query(query, exclude_negated, hide_duplicates,
                    skip_after_event, tag_query):
    
    db.save_query(query, exclude_negated, hide_duplicates,
                    skip_after_event, tag_query)
    
    curr_query_str = db.get_search_query()
    
    assert curr_query_str == query

    all_queries = db_session.query(QUERY).all()
    non_curr_queries = db_session.query(QUERY).filter(QUERY.current == False).all()
    # Ensure only one query is current at a time
    assert len(non_curr_queries) + 1 == len(all_queries)

@pytest.mark.app
def test_upload_notes():
    '''
    Tests for insertion into the notes and patients tables.
    '''
    db.upload_notes(test_data)

    for index, row in test_data.iterrows():
        note = db_session.query(NOTES).filter(NOTES.text_id == row['text_id']).first()

        date_format = '%Y-%m-%d'
        datetime_obj = datetime.datetime.strptime(row["text_date"], date_format)

        # We replace these so that SQLalchemy reads " characters as literals in the string
        assert note.text_id == row['text_id'].replace('"', '""')
        assert note.text == row['text'].replace('"', '""')
        assert note.patient_id == row['patient_id']
        assert note.text_date == datetime_obj
        assert note.doc_id == row['doc_id'].replace('"', '""')
        assert note.text_sequence == row['text_sequence']
        assert note.text_tag_1 == row['text_tag_1'].replace('"', '""')
        assert note.text_tag_2 == row['text_tag_2'].replace('"', '""')
        assert note.text_tag_3 == row['text_tag_3'].replace('"', '""')
        assert note.text_tag_4 == row['text_tag_4'].replace('"', '""')
    
    patient_ids = test_data['patient_id'].unique()
    patient_ids = [int(i) for i in patient_ids]
    assert db.get_patient() in patient_ids
    for p_id in patient_ids:
        patient = db_session.query(PATIENTS).filter(PATIENTS.patient_id == p_id).first()

        assert patient is not None
        assert patient.patient_id == p_id
        assert not patient.reviewed
        assert not patient.locked
        assert not patient.admin_locked
        assert not patient.updated

@pytest.mark.app
def test_insert_annotations():
    for index, row in test_data.iterrows():
        annotation = {}

        annotation['note_id'] = row['text_id'].replace('"', '""')
        annotation["sentence"] = row['text'].replace('"', '""').split(". ")[0]
        annotation['token'] = 'example token'
        annotation["lemma"] = 'example lemma'
        annotation["isNegated"] = False
        annotation["start_index"] = 1
        annotation["end_index"] = 5
        annotation["note_start_index"] = 0
        annotation["note_end_index"] = 10
        annotation["sentence_number"] = 1
        annotation["patient_id"] = row['patient_id']
        annotation["event_date"] = None
        annotation["reviewed"] = False

        db.insert_one_annotation(annotation)

        if index == 0:
            # testing multipule annos for a single note

            for i in range(1, 4):
                annotation["sentence"] = row['text'].replace('"', '""').split(". ")[i]
                annotation["sentence_number"] = i + 1
                db.insert_one_annotation(annotation)
            
            annos = db.get_all_annotations_for_note(row['text_id'])

            assert len(annos) == 4

            for i in range(len(annos)):
                assert annos[i]['note_id'] == row['text_id']
                assert annos[i]["sentence"] == row['text'].replace('"', '""').split(". ")[i]
                assert annos[i]['token'] == 'example token'
                assert annos[i]["lemma"] == 'example lemma'
                assert annos[i]["isNegated"] is False
                assert annos[i]["start_index"] == 1
                assert annos[i]["end_index"] == 5
                assert annos[i]["note_start_index"] == 0
                assert annos[i]["note_end_index"] == 10
                assert annos[i]["sentence_number"] == i + 1
                assert annos[i]["patient_id"] == row['patient_id']
                assert annos[i]["event_date"] is None
                assert annos[i]["reviewed"] is False

@pytest.mark.app
def test_search_anno():
    
    test_anno = db_session.query(ANNOTATIONS).first()
    test_anno = db.row_to_dict(test_anno)

    db_anno = db.get_annotation(test_anno['anno_id'])

    for key in test_anno:
        assert test_anno[key] == db_anno[key]
    
    db_note = db.get_annotation_note(test_anno['anno_id'])

    note_id = test_anno["note_id"]
    test_note = db_session.query(NOTES).filter(NOTES.text_id == note_id).first()
    test_note = db.row_to_dict(test_note)

    for key in test_note:
        assert test_note[key] == db_note[key]

@pytest.mark.app
def test_get_patient_annotation_ids():
    patients = db_session.query(PATIENTS).all()
    patient_ids = [int(i.patient_id) for i in patients]

    for p_id in patient_ids:
        anno_ids = db.get_patient_annotation_ids(p_id)
        annos = db_session.query(ANNOTATIONS)
        for a_id in anno_ids:
            anno = annos.filter(ANNOTATIONS.anno_id == a_id).first()

            assert anno.patient_id == p_id

@pytest.mark.app
def test_mark_annotation_reviewed():
    test_anno = db_session.query(ANNOTATIONS).first()

    db.mark_annotation_reviewed(test_anno.anno_id)

    updated_anno = db_session.query(ANNOTATIONS)
    updated_anno = updated_anno.filter(ANNOTATIONS.anno_id == test_anno.anno_id).first()

    assert updated_anno.reviewed is True

@pytest.mark.app
@pytest.mark.parametrize("new_date", [("2023-05-01"), ("1995-12-31"), (None)])
def test_annotation_date(new_date):
    test_anno = db_session.query(ANNOTATIONS).first()

    db.update_annotation_date(test_anno.anno_id, new_date)

    updated_anno = db_session.query(ANNOTATIONS)
    updated_anno = updated_anno.filter(ANNOTATIONS.anno_id == test_anno.anno_id).first()

    if new_date is not None:
        date_obj = datetime.datetime.strptime(new_date, "%Y-%m-%d")
        assert updated_anno.event_date == date_obj

        assert date_obj == db.get_annotation_date(test_anno.anno_id)

        db.delete_annotation_date(test_anno.anno_id)

        updated_anno = db_session.query(ANNOTATIONS)
        updated_anno = updated_anno.filter(ANNOTATIONS.anno_id == test_anno.anno_id).first()

    assert updated_anno.event_date is None

@pytest.mark.app
@pytest.mark.parametrize("status", [(True), (False)])
def test_mark_patient_reviewed(status):
    patient = db_session.query(PATIENTS).first()
    test_id = patient.patient_id

    db.mark_patient_reviewed(test_id, status)

    updated_patient = db_session.query(PATIENTS)
    updated_patient = updated_patient.filter(PATIENTS.patient_id == test_id).first()

    assert updated_patient.reviewed is status



@pytest.mark.app
@pytest.mark.parametrize("a_id, comments", [(1, ['This is a comment.']),
                                            (2, ['C1', 'C2', 'C3']),
                                            (3, [])])
def test_annotation_comment(a_id, comments):
    for comment in comments:
        db.add_annotation_comment(a_id, comment)

    db_comms = db.get_comments(a_id)

    assert len(comments) == len(db_comms)

    for comment in comments:
        assert comment in db_comms

@pytest.mark.app
def test_empty_annotations():
    db.empty_annotations()

    annos = db_session.query(ANNOTATIONS).all()

    assert len(annos) == 0

@pytest.mark.app
def test_get_all_annotations():
    db.empty_annotations()

    annotation = {}

    for i in range(5):
        annotation['note_id'] = f"n_{i}"
        annotation["sentence"] = f"s_{i}"
        annotation['token'] = f'example token {i % 2}'
        annotation["lemma"] = f'example lemma {i % 2}'
        annotation["isNegated"] = False
        annotation["start_index"] = 1
        annotation["end_index"] = 5
        annotation["note_start_index"] = 0
        annotation["note_end_index"] = 10
        annotation["sentence_number"] = i + 1
        annotation["patient_id"] = f"p_{i % 2}"
        annotation["event_date"] = None
        annotation["reviewed"] = False

        db.insert_one_annotation(annotation)

    db_annos = db.get_all_annotations()

    for i in range(5):
        annotation['note_id'] = f"n_{i}"
        annotation["sentence"] = f"s_{i}"
        annotation['token'] = f'example token {i % 2}'
        annotation["lemma"] = f'example lemma {i % 2}'
        annotation["sentence_number"] = i + 1
        annotation["patient_id"] = f"p_{i % 2}"

        for db_anno in db_annos:
            if db_anno["note_id"] == f"n_{i}":
                for key in annotation:
                    assert annotation[key] == db_anno[key]
                
                break


@pytest.mark.app
def test_get_curr_stats():
    # Note that annotations are already in db from test_get_all_annotations

    stats = db.get_curr_stats()

    assert stats['number_of_patients'] == 5
    assert stats['number_of_annotated_patients'] == 2
    assert stats['number_of_reviewed'] == 0
    assert stats['lemma_dist']['example lemma 0'] == 3
    assert stats['lemma_dist']['example lemma 1'] == 2

    # mark patient 1's records as annotated
    db.mark_annotation_reviewed(1)
    db.mark_annotation_reviewed(3)

    # test that the reviews are reflected in the stats
    stats = db.get_curr_stats()

    assert stats['number_of_patients'] == 5
    assert stats['number_of_annotated_patients'] == 2
    assert stats['number_of_reviewed'] == 1
    assert stats['lemma_dist']['example lemma 0'] == 3
    assert stats['lemma_dist']['example lemma 1'] == 2

@pytest.mark.app
def test_get_all_patients():
    # these patients data are loaded from the example csv file
    db_patients = db.get_all_patients()

    assert len(db_patients) == 5

    p_ids = [1111111111, 2222222222, 3333333333, 4444444444, 5555555555]

    db_p_ids = [i['patient_id'] for i in db_patients]

    db_p_ids.sort()

    for i in range(len(db_p_ids)):
        assert db_p_ids[i] == p_ids[i]

@pytest.mark.app
@pytest.mark.parametrize("p_id, status", [(1111111111, True),
                                          (2222222222, False)])
def test_patient_locks(p_id, status):
    # set_patient_lock_status
    # get_patient_lock_status

    db.set_patient_lock_status(p_id, status)

    patient_data = db_session.query(PATIENTS).filter(PATIENTS.patient_id == p_id).first()

    assert patient_data.locked is status
    assert db.get_patient_lock_status(p_id) is status

@pytest.mark.app
def test_remove_all_locked():
    db.set_patient_lock_status(1111111111, True)
    db.set_patient_lock_status(2222222222, True)
    db.remove_all_locked()
    patients = db_session.query(PATIENTS).all()
    for patient in patients:
        assert patient.locked is False

@pytest.mark.app
@pytest.mark.parametrize("p_id", [(1111111111),(2222222222)])
def test_get_patient_notes(p_id):
    db_notes = db.get_patient_notes(p_id)

    note_data = db_session.query(NOTES).filter(NOTES.patient_id == p_id).all()

    notes = [db.row_to_dict(row) for row in note_data]

    for note in notes:
        note_found = False
        for db_note in db_notes:
            if note['text_id'] == db_note['text_id']:
                for key in note:
                    assert note[key] == db_note[key]

                note_found = True
                break
            
        # every note must match a db_note
        # if not this line will be reached and an error will be thrown
        if not note_found:
            raise Exception(f"Note with id {note['text_id']} for patient {p_id} not returned.")