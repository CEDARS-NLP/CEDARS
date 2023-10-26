"""
This file contatins an abstract class for CEDARS to interact with sqlite3.
"""

from datetime import datetime
import os
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv
from bson import ObjectId
from sqlalchemy import text
import logging
from .database import db_conn

load_dotenv()


def create_project(project_name, investigator_name, cedars_version):
    """
    This function creates all the collections in the sqlite3 database for CEDARS.

    Args:
        project_name (str) : Name of the research project
        investigator_name (str) : Name of the investigator on this project
        cedars_version (str) : Version of CEDARS used for this project
    Returns:
        None
    """
    
    result = db_conn.execute(text("SELECT name FROM sqlite_master WHERE type='table';"))
    tables = [row[0] for row in result.fetchall()]

    if "INFO" in tables:
        logging.info("Database already created.")
        return

    create_info_col(project_name, investigator_name, cedars_version)

    populate_patients()
    populate_notes()
    populate_annotations()
    populate_users()
    populate_query()

    logging.info("Database creation successful!")

def create_info_col(project_name, investigator_name, cedars_version):
    """
    This function creates the info table in the sqlite3 database.
    The info table is used to store meta-data regarding the current project.

    Args:
        project_name (str) : Name of the research project
        investigator_name (str) : Name of the investigator on this project
        cedars_version (str) : Version of CEDARS used for this project
    Returns:
        None
    """
    db_conn.execute(text("""CREATE TABLE INFO (
                                            project_name varchar(255),
                                            investigator_name varchar(255),
                                            cedars_version varchar(255),
                                            creation_time DATETIME
                                            );"""))

    command = "INSERT INTO INFO VALUES('{}', '{}', '{}', datetime('now'));".format(project_name, investigator_name,
                                                                cedars_version)
    db_conn.execute(text(command))

    db_conn.commit()
    logging.info("Created INFO table.")

def get_info():
    """
    This function returns the info table in the sqlite3 database.

    Args:
        None
    Returns:
        dict : {column name : value}
    """
    result = db_conn.execute(text("SELECT * FROM INFO LIMIT 1;"))
    info = result.fetchall()[0]

    # get column names from INFO table
    result = db_conn.execute(text("PRAGMA table_info(INFO);"))
    column_names = [row[1] for row in result.fetchall()]

    info_dict = {}
    for i in range(len(info)):
        info_dict[column_names[i]] = info[i]

    return info_dict


def populate_annotations():
    """
    This function creates the annotations and patients tables in the sqlite3 database.
    The annotations table is used to store the NLP annotations generated by our NLP model.
    The patients table is used to store the patient ids as well as their current status.

    Args:
        None
    Returns:
        None
    """
    db_conn.execute(text("""CREATE TABLE ANNOTATIONS (
                                            anno_id integer primary key AUTOINCREMENT,
                                            note_id integer,
                                            sentence text(10000),
                                            token varchar(50),
                                            lemma varchar(50),
                                            isNegated boolean,
                                            start_index integer,
                                            end_index integer,
                                            note_start_index integer,
                                            note_end_index integer,
                                            sentence_number integer,
                                            patient_id integer,
                                            event_date date,
                                            reviewed boolean,
                                            FOREIGN KEY (note_id) REFERENCES NOTES(text_id)
                                            FOREIGN KEY (patient_id) REFERENCES PATIENTS(patient_id)
                                            );"""))


    logging.info("Created ANNOTATIONS table.")

    db_conn.execute(text("""CREATE TABLE COMMENTS (
                                            comm_id integer primary key AUTOINCREMENT,
                                            anno_id integer,
                                            comment text(10000),
                                            FOREIGN KEY (anno_id) REFERENCES ANNOTATIONS(anno_id)
                                            );"""))


    logging.info("Created COMMENTS table.")

    db_conn.commit()

def populate_notes():
    """
    This function creates the notes table in the sqlite3 database.
    This table is used to store the patient's medical records.
    """
    db_conn.execute(text("""CREATE TABLE NOTES (
                                            text_id varchar(50) primary key,
                                            text MEDIUMTEXT(10000),
                                            patient_id integer,
                                            text_date date,
                                            doc_id varchar(50),
                                            text_sequence integer,
                                            text_tag_1 varchar(50),
                                            text_tag_2 varchar(50),
                                            text_tag_3 varchar(50),
                                            text_tag_4 varchar(50),
                                            FOREIGN KEY (patient_id) REFERENCES PATIENTS(patient_id)
                                            );"""))

    logging.info("Created NOTES table.")
    db_conn.commit()


def populate_patients():
    """
    This function creates the patients table in the sqlite3 database.
    This table is used to store the patient's medical records.
    """
    db_conn.execute(text("""CREATE TABLE PATIENTS (
                                            patient_id integer primary key,
                                            reviewed boolean,
                                            locked boolean,
                                            updated boolean,
                                            admin_locked boolean                      
                                            );"""))
    logging.info("Created PATIENTS table.")
    db_conn.commit()

def populate_users():
    """
    This function creates the users table in the sqlite3 database.
    This table is used to store the credentials of users of the CEDARS system.
    """
    db_conn.execute(text("""CREATE TABLE USERS (
                                            _id integer primary key AUTOINCREMENT,
                                            user varchar(100),
                                            password varchar(200),
                                            is_admin boolean,
                                            date_created datetime                      
                                            );"""))
    logging.info("Created USERS collection.")
    db_conn.commit()

def populate_query():
    """
    This function creates the query table in the sqlite3 database.
    This table is used to store the regex queries that researchrs are using.
    """

    db_conn.execute(text("""CREATE TABLE QUERY (
                                            query varchar(200),
                                            tag_query_include varchar(200),
                                            tag_query_exclude varchar(200),
                                            exclude_negated boolean,
                                            hide_duplicates boolean,
                                            skip_after_event boolean,
                                            tag_query_exact boolean,
                                            tag_query_nlp_apply boolean,
                                            current boolean,
                                            date_min date,
                                            date_max date
                                            );"""))
    
    logging.info("Created QUERY collection.")
    db_conn.commit()


def get_user(username):
    """
    This function is used to get a user from the database.

    Args:
        username (str) : The name of the user to get.
    Returns:
        user (dict) : The user object from the database.
    """

    result = db_conn.execute(text("SELECT * FROM USERS WHERE user = '{}';".format(username)))
    user_data = result.fetchall()

    if len(user_data) == 0:
        return None
    
    user_data = user_data[0] # first row

    # get column names from USERS table
    result = db_conn.execute(text("PRAGMA table_info(USERS);"))
    column_names = [row[1] for row in result.fetchall()]

    users_dict = {}
    for i in range(len(user_data)):
        users_dict[column_names[i]] = user_data[i]

    users_dict['is_admin'] = bool(eval(users_dict['is_admin'])) # is string by default so we convert to bool

    return users_dict

def add_user(username, password, is_admin=False):
    """
    This function is used to add a new user to the database.
    All this data is kept in the USERS table.

    Args:
        username (str) : The name of this user.
        password (str) : The password this user will need to login to the system.
    Returns:
        None
    """

    command = """INSERT INTO USERS(user, password, is_admin, date_created)
                    VALUES('{}', '{}', '{}', datetime('now'));""".format(username, password,
                                                                                    is_admin)
    db_conn.execute(text(command))
    

    db_conn.commit()
    logging.info("Added user %s to database.", username)

# Pylint disabled due to too many arguments
def save_query(query, exclude_negated, hide_duplicates, #pylint: disable=R0913
                skip_after_event, tag_query, date_min = None, date_max = None):

    """
    This function is used to save a regex query to the database.
    All this data is kept in the QUERY table.

    Args:
        query (str) : The regex query.
        exclude_negated (bool) : True if we want to exclude negated tokens.
        hide_duplicates (bool) : True if we want to restrict duplicate queries.
        skip_after_event (bool) : True if sentences occurring
                                    after a recorded clinical event are to be skipped.
        tag_query (dict of mapping [str : list]) :
                                    Key words to include or exclude in the search.
        date_min (str) : Smallest date for valid query.
        date_max (str) : Greatest date for valid query.
    Returns:
        None
    """
    # only one query is current at a time.
    db_conn.execute(text("UPDATE QUERY SET current=FALSE;"))
    # TODO: make a query history and enable multiple queries.
    

    command = "INSERT INTO QUERY VALUES('{}', '{}', '{}', {}, {}, {}, {}, {}, TRUE, NULL, NULL);".format(
                                                                   query, tag_query["include"][0],
                                                                   tag_query["exclude"][0],
                                                                   exclude_negated, hide_duplicates,
                                                                   skip_after_event, tag_query["exact"][0],
                                                                   tag_query["nlp_apply"][0])
    db_conn.execute(text(command))

    db_conn.commit()
    logging.info("Saved query : %s.", query)


def get_search_query():
    """
    This function is used to get the current search query from the database.
    All this data is kept in the QUERY table.

    Args:
        None
    Returns:
        current search query (string) : The query where current is TRUE.
    """
    result = db_conn.execute(text("SELECT query FROM QUERY WHERE current = TRUE LIMIT 1;"))
    query_data = result.fetchall()

    if len(query_data) > 0:
        return query_data[0][0]
    else:
        return None


def upload_notes(documents):
    """
    This function is used to take a dataframe of patient records
    and save it to the sqlite database.

    Args:
        documents (pandas dataframe) : Dataframe with all the records of a paticular patient.
    Returns:
        None
    """

    patient_ids = set()
    for i in range(len(documents)):
        note_info = documents.iloc[i].to_dict()

        date_format = '%Y-%m-%d'
        datetime_obj = datetime.strptime(note_info["text_date"], date_format)
        note_info["text_date"] = datetime_obj

        # check if text_id exists in database
        is_present = db_conn.execute(text("select '{}' in (select text_id from NOTES);".format(note_info["text_id"])))
        is_present = is_present.fetchall()[0][0] # row 1 column 1

        if is_present:
            logging.error("Cancelling duplicate note entry")
        else:
            insert_command = """INSERT INTO NOTES VALUES("{}", "{}", {}, "{}",
                                                         "{}", {},
                                                         "{}", "{}", "{}", "{}");"""
            insert_command = insert_command.format(note_info["text_id"].replace('"', '""'),
                                                    note_info["text"].replace('"', '""'),
                                                    note_info["patient_id"],
                                                    note_info["text_date"],
                                                    note_info["doc_id"].replace('"', '""'),
                                                    note_info["text_sequence"],
                                                    note_info["text_tag_1"].replace('"', '""'),
                                                    note_info["text_tag_2"].replace('"', '""'),
                                                    note_info["text_tag_3"].replace('"', '""'),
                                                    note_info["text_tag_4"].replace('"', '""'))



            db_conn.execute(text(insert_command))
            patient_ids.add(note_info["patient_id"])

    for p_id in patient_ids:
        patient_info = {"patient_id": p_id,
                        "reviewed": False,
                        "locked": False,
                        "updated": False,
                        "admin_locked": False}

         # check if patient already exists in database
        is_present = db_conn.execute(text("select '{}' in (select patient_id from PATIENTS);".format(p_id)))
        is_present = is_present.fetchall()[0][0] # row 1 column 1
        
        if not is_present:
            insert_command = """INSERT INTO PATIENTS
                                            VALUES({}, FALSE, FALSE, FALSE, FALSE);""".format(p_id)
            db_conn.execute(text(insert_command))
    
    db_conn.commit()

def  get_all_annotations_for_note(note_id):
    """
    This function is used to get all the annotations for a particular note.
    """
    result = db_conn.execute(text("""SELECT * FROM ANNOTATIONS
                                                WHERE note_id = "{}"
                                                ORDER BY note_start_index
                                  ;""".format(note_id)))
    anno_data = result.fetchall()

    # get column names from ANNOTATIONS table
    result = db_conn.execute(text("PRAGMA table_info(ANNOTATIONS);"))
    column_names = [row[1] for row in result.fetchall()]

    annotations = []
    for i in range(len(anno_data)):
        annotations.append({})
        for j in range(len(column_names)):
            annotations[-1][column_names[j]] = anno_data[i][j]


    return annotations


def get_annotation(annotation_id):
    """
    Retrives annotation from sqlite3.

    Args:
        annotation_id (str) : Unique ID for the annotation.
    Returns:
        annotation (dict) : Dictionary for an annotation from sqlite3.
            The keys are the attribute names.
            The values are the values of the attribute in that record.
    """

    result = db_conn.execute(text("""SELECT * FROM ANNOTATIONS
                                                WHERE anno_id = {}
                                                LIMIT 1
                                  ;""".format(annotation_id)))
    anno_data = result.fetchall()[0]

    # get column names from ANNOTATIONS table
    result = db_conn.execute(text("PRAGMA table_info(ANNOTATIONS);"))
    column_names = [row[1] for row in result.fetchall()]

    annotation = {}
    for j in range(len(column_names)):
        annotation[column_names[j]] = anno_data[j]


    return annotation
 
def get_annotation_note(annotation_id):
    """
    Retrives note linked to a paticular annotation.

    Args:
        annotation_id (str) : Unique ID for the annotation.
    Returns:
        note (dict) : Dictionary for a note from mongodb.
                      The keys are the attribute names.
                      The values are the values of the attribute in that record.
    """
    logging.debug("Retriving annotation #%s from database.", annotation_id)
    
    select_command = """SELECT * FROM NOTES WHERE text_id in 
                    (SELECT note_id FROM ANNOTATIONS WHERE anno_id = {});""".format(annotation_id)

    result = db_conn.execute(text(select_command))
    note_data = result.fetchall()[0]

    # get column names from NOTES table
    result = db_conn.execute(text("PRAGMA table_info(NOTES);"))
    column_names = [row[1] for row in result.fetchall()]

    note = {}
    for j in range(len(column_names)):
        note[column_names[j]] = note_data[j]
        
    return note


def get_patient():
    """
    Retrives a single patient ID who has not yet been reviewed and is not currently locked.
    The chosen patient is simply the first one in the database that has not yet been reviewed.

    Args:
        None
    Returns:
        patient_id (int) : Unique ID for a patient.
    """

    select_command = """SELECT patient_id FROM PATIENTS
                                WHERE reviewed = FALSE AND locked = FALSE
                                LIMIT 1;"""
    
    result = db_conn.execute(text(select_command))
    patient_data = result.fetchall()

    if len(patient_data) > 0:
        p_id = patient_data[0][0]
        logging.debug("Retriving patient #%s from database.", p_id)
        return p_id

    logging.debug("Failed to retrive any further un-reviewed patients from the database.")
    return None

def get_patient_annotation_ids(p_id):
    """
    Retrives all annotation IDs for annotations linked to a patient.

    Args:
        p_id (int) : Unique ID for a patient.
    Returns:
        annotations (list) : A list of all annotation IDs linked to that patient.
    """
    logging.debug("Retriving annotations for patient #%s from database.", str(p_id))

    if p_id == None:
        return []
    
    select_command = """SELECT anno_id FROM ANNOTATIONS
                                        WHERE patient_id = {} AND
                                        reviewed = FALSE AND
                                        isNegated = FALSE;""".format(p_id)
    
    result = db_conn.execute(text(select_command))
    annotation_data = result.fetchall()

    return [str(row[0]) for row in annotation_data]

def mark_annotation_reviewed(annotation_id):
    """
    Updates the annotation in the database to mark it as reviewed.

    Args:
        annotation_id (str) : Unique ID for the annotation.
    Returns:
        None
    """
    logging.debug("Marking annotation #%s as reviewed.", annotation_id)

    db_conn.execute(text("UPDATE ANNOTATIONS SET reviewed=TRUE WHERE anno_id={};".format(annotation_id)))
    db_conn.commit()

def update_annotation_date(annotation_id, new_date):
    """
    Enters a new event date for an annotation.

    Args:
        annotation_id (str) : Unique ID for the annotation.
        new_date (str) : The new value to update the event date of an annotation with.
            Must be in the format YYYY-MM-DD .
    Returns:
        None
    """
    # TODO: UTC dates
    logging.debug("Updating date on annotation #%s to %s.", annotation_id, new_date)

    db_conn.execute(text("UPDATE ANNOTATIONS SET event_date='{}' WHERE anno_id={};".format(new_date,
                                                                                    annotation_id)))
    
    db_conn.commit()

def delete_annotation_date(annotation_id):
    """
    Deletes the event date for an annotation.

    Args:
        annotation_id (str) : Unique ID for the annotation.
    Returns:
        None
    """
    logging.debug("Deleting date on annotation #%s.", annotation_id)
    db_conn.execute(text("UPDATE ANNOTATIONS SET event_date=NULL WHERE anno_id={};".format(annotation_id)))
    
    db_conn.commit()

def get_annotation_date(annotation_id):
    """
    Retrives the event date for an annotation.
    """
    logging.debug("Retriving date on annotation #%s.", annotation_id)

    select_command = """SELECT event_date FROM ANNOTATIONS
                                        WHERE anno_id = {};""".format(annotation_id)
    
    result = db_conn.execute(text(select_command))
    annotation_data = result.fetchall()

    if len(annotation_data) > 0:
        return annotation_data[0][0]

    return None


def mark_patient_reviewed(patient_id, is_reviewed = True):
    """
    Updates the patient's status to reviewed in the database.

    Args:
        patient_id (int) : Unique ID for a patient.
        is_reviewed (bool) : True if patient's annotations have been reviewed.
    Returns:
        None
    """
    logging.debug("Marking patient #%s as reviewed.", patient_id)
    if patient_id is None:
        return

    db_conn.execute(text("UPDATE PATIENTS SET reviewed={} WHERE patient_id={};".format(is_reviewed,
                                                                                          patient_id)))
    
    db_conn.commit()

def add_annotation_comment(annotation_id, comment):
    """
    Stores a new comment for an annotation.

    Args:
        annotation_id (str) : Unique ID for the annotation.
        comment (str) : Text of the comment on this annotation.
    Returns:
        None
    """
    logging.debug("Adding comment to annotation #%s.", annotation_id)

    db_conn.execute(text("""INSERT INTO COMMENTS (anno_id, comment)
                         VALUES('{}', '{}');""".format(annotation_id, comment)))
    
    db_conn.commit()

def empty_annotations():
    """
    Deletes all annotations from the database.
    """

    logging.info("Deleting all data in annotations collection.")
    db_conn.execute(text("DELETE FROM ANNOTATIONS;"))
    db_conn.commit()

def get_all_annotations():
    """
    Returns a list of all annotations from the database.

    Args:
        None
    Returns:
        Annotations (list) : This is a list of all annotations from the database.
    """

    result = db_conn.execute(text("""SELECT * FROM ANNOTATIONS;"""))
    anno_data = result.fetchall()

    # get column names from ANNOTATIONS table
    result = db_conn.execute(text("PRAGMA table_info(ANNOTATIONS);"))
    column_names = [row[1] for row in result.fetchall()]

    annotations = []
    for i in range(len(anno_data)):
        annotations.append({})
        for j in range(len(column_names)):
            annotations[-1][column_names[j]] = anno_data[i][j]

    return list(annotations)

def get_comments(annotation_id):
    result = db_conn.execute(text("""SELECT comment FROM COMMENTS
                                  WHERE anno_id={};""".format(annotation_id)))
    data = result.fetchall()

    return [row[0] for row in data] # select the first column only

def get_proj_name():
    """
    Returns the name of the current project.

    Args:
        None
    Returns:
        proj_name (str) : The name of the current CEDARS project.
    """

    result = db_conn.execute(text("SELECT project_name FROM INFO LIMIT 1;"))
    data = result.fetchall()

    if len(data) > 0:
        return data[0][0]
    else:
        return None

def update_project_name(new_name):
    """
    Updates the project name in the INFO collection of the database.

    Args:
        new_name (str) : New name of the project.
    Returns:
        None
    """
    logging.debug("Updating project name to #%s.", new_name)

    db_conn.execute(text("UPDATE INFO SET project_name='{}';".format(new_name)))
    
    db_conn.commit()


def get_curr_version():
    """
    Returns the name of the current project.

    Args:
        None
    Returns:
        proj_name (str) : The name of the current CEDARS project.
    """

    result = db_conn.execute(text("SELECT cedars_version FROM INFO LIMIT 1;"))
    data = result.fetchall()

    if len(data) > 0:
        return data[0][0]
    else:
        return None

def add_project_user(username, password, is_admin = False):
    """
    Adds a new user to the project database.

    Args:
        username (str)  : The name of the new user
        password (str)  : The user's password
        is_admin (bool) : True if the new user is the project admin
                          (used when initializing the project)
    Returns:
        None
    """
    password_hash = generate_password_hash(password)
    add_user(username, password_hash, is_admin)

def check_password(username, password):
    """
    Checks if the password matches the password of that user from the database.

    Args:
        username (str) : The name of the new user
        password (str) : The password entered by the user.

    Returns:
        (bool) : True if the password matches the password of that user from the database.
    """

    result = db_conn.execute(text("SELECT password FROM USERS WHERE user={};".format(username)))
    user_pass = result.fetchall()

    if len(user_pass) > 0:
        return check_password_hash(user_pass[0][0], password)
    else:
        return None


def get_project_users():
    """
    Returns all the usernames for approved users (including the admin) for this project

    Args:
        None
    Returns:
        usernames (list) : List of all usernames for approved users
                           (including the admin) for this project
    """

    result = db_conn.execute(text("SELECT user FROM USERS;"))
    users = result.fetchall()

    return [users[0] for user in users]


def get_curr_stats():
    """
    Returns basic statistics for the project

    Args:
        None
    Returns:
        stats (list) : List of basic statistics for the project. These include :
            1. number_of_patients (number of unique patients in the database)
            2. number_of_annotated_patients (number of patiens who had notes
                in which key words were found)
            3. number_of_reviewed
                        (number of patients who have been reviewed for the current query)
    """
    # TODO: use aggregation pipeline
    stats = {}
    patients = get_all_patients()

    stats["number_of_patients"] = len(list(patients))

    result = db_conn.execute(text("""SELECT patient_id FROM ANNOTATIONS
                                  WHERE isNegated=FALSE;"""))
    annotations = result.fetchall()
    unique_patients = {annotation[0] for annotation in annotations}

    stats["number_of_annotated_patients"] = len(unique_patients)

    num_reviewed_annotations = 0

    for p_id in unique_patients:
        result = db_conn.execute(text("""SELECT reviewed FROM ANNOTATIONS
                                  WHERE patient_id={};""".format(p_id)))
        is_reviewed = result.fetchall()[0][0]

        if is_reviewed:
            num_reviewed_annotations += 1

    stats["number_of_reviewed"] = num_reviewed_annotations

    lemma_dist = {}
    result = db_conn.execute(text("""SELECT lemma FROM ANNOTATIONS
                                  WHERE isNegated=FALSE;"""))
    annotations = result.fetchall()
    for anno in annotations:
        lemma = anno[0] # get the first column from results
        if lemma in lemma_dist:
            lemma_dist[lemma] += 1
        else:
            lemma_dist[lemma] = 1

    stats['lemma_dist'] = lemma_dist

    return stats

def get_all_patients():
    """
    Returns all the patients in this project

    Args:
        None
    Returns:
        patients (list) : List of all patients in this project
    """

    result = db_conn.execute(text("SELECT * FROM PATIENTS;"))
    patient_data = result.fetchall()

    # get column names from PATIENTS table
    result = db_conn.execute(text("PRAGMA table_info(PATIENTS);"))
    column_names = [row[1] for row in result.fetchall()]

    patients = []
    for i in range(len(patient_data)):
        patients.append({})
        for j in range(len(column_names)):
            patients[-1][column_names[j]] = patient_data[i][j]


    return patients

def set_patient_lock_status(patient_id, status):
    """
    Updates the status of the patient to be locked or unlocked.

    Args:
        patient_id (int) : ID for the patient we are locking / unlocking
        status (bool) : True if the patient is being locked, False otherwise.

    Returns:
        None
    """

    db_conn.execute(text("UPDATE PATIENTS SET locked={} WHERE patient_id={};".format(status,
                                                                                patient_id)))
    db_conn.commit()

def get_patient_lock_status(patient_id):
    """
    Returns true if the patient is locked, false otherwise.

    Args:
        patient_id (int) : ID for the patient we are locking / unlocking
    Returns:
        status (bool) : True if the patient is locked, False otherwise.
            If no such patient is found, we return None.

    Raises:
        None
    """
    result = db_conn.execute(text("SELECT locked FROM PATIENTS WHERE patient_id={};".format(patient_id)))
    patient_data = result.fetchall()
    return patient_data[0][0]


def get_patient_notes(patient_id):
    """
    Returns all notes for that patient.

    Args:
        patient_id (int) : ID for the patient
    Returns:
        notes (list) : A list of all notes for that patient
    """

    result = db_conn.execute(text("""SELECT * FROM NOTES
                                  WHERE patient_id={};""".format(patient_id)))
    note_data = result.fetchall()

    # get column names from NOTES table
    result = db_conn.execute(text("PRAGMA table_info(NOTES);"))
    column_names = [row[1] for row in result.fetchall()]

    notes = []
    for i in range(len(note_data)):
        notes.append({})
        for j in range(len(column_names)):
            notes[-1][column_names[j]] = note_data[i][j]

    return notes

def insert_one_annotation(annotation):
    """
    Adds an annotation to the database.

    Args:
        annotation (dict) : The annotation we are inserting
    Returns:
        None
    """

    insert_command = """INSERT INTO ANNOTATIONS(note_id, sentence, token, lemma,
                                                isNegated, start_index, end_index,
                                                note_start_index, note_end_index,
                                                sentence_number, patient_id,
                                                event_date, reviewed)
                            VALUES("{}", "{}", "{}", "{}",
                                    {}, {}, {}, {}, {},
                                    {}, {}, "{}", {}
                                        );""".format(annotation["note_id"].replace('"', '""'),
                                                     annotation["sentence"].replace('"', '""'),
                                                     annotation["token"].replace('"', '""'),
                                                     annotation["lemma"].replace('"', '""'),
                                                     annotation["isNegated"],
                                                     annotation["start_index"],
                                                     annotation["end_index"],
                                                     annotation["note_start_index"],
                                                     annotation["note_end_index"],
                                                     annotation["sentence_number"],
                                                     annotation["patient_id"],
                                                     annotation["event_date"],
                                                     annotation["reviewed"])


    db_conn.execute(text(insert_command))
    db_conn.commit()

def remove_all_locked():
    """
    Sets the locked status of all patients to False.
    This is done when the server is shutting down.
    """
    db_conn.execute(text("UPDATE PATIENTS SET locked=FALSE;"))
    db_conn.commit()

def is_admin_user(username):
    """check if the user is admin"""

    result = db_conn.execute(text("SELECT is_admin FROM USERS WHERE user={};".format(username)))
    result = result.fetchall()

    # result[0][0] = is_admin as it is the first row and column
    if len(result) > 0 and result[0][0]:
        return True

    return False


def drop_database(name):
    """Clean Database"""
    os.remove(f"{name}.db")
