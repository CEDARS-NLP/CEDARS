"""
This file contatins an abstract class for CEDARS to interact with sqlalchemy.
"""

from datetime import datetime
import os
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv
import sqlalchemy
from sqlalchemy import and_
import logging
from .database import db_session, db_engine, Base
from .sqlalchemy_tables import INFO, PATIENTS, NOTES, QUERY
from .sqlalchemy_tables import ANNOTATIONS, COMMENTS, USERS

load_dotenv()

def row_to_dict(row):
    '''
    This function converts an sqlalchemy object for a table entry to a dictionary that maps 
        {column_name : value}

    Args:
        row (obj of class derived from sqlalchemy's DeclarativeBase class)
            : An object representing a single entry in a table.
    Returns:
        dict : {column_name : value} for that database entry
    '''

    row = dict(row.__dict__)
    row.pop('_sa_instance_state')

    return row


def create_project(project_name, investigator_name, cedars_version):
    """
    This function creates all the collections in the sqlalchemy database for CEDARS.

    Args:
        project_name (str) : Name of the research project
        investigator_name (str) : Name of the investigator on this project
        cedars_version (str) : Version of CEDARS used for this project
    Returns:
        None
    """
    
    exists = sqlalchemy.inspect(db_engine).has_table("INFO")

    if exists:
        logging.info("Database already created.")
        return

    Base.metadata.create_all(db_engine)
    logging.info("Database creation successful!")

    create_info_col(project_name, investigator_name, cedars_version)

    logging.info("Project information added to database.")

def create_info_col(project_name, investigator_name, cedars_version):
    """
    This function creates the info table in the sqlalchemy database.
    The info table is used to store meta-data regarding the current project.

    Args:
        project_name (str) : Name of the research project
        investigator_name (str) : Name of the investigator on this project
        cedars_version (str) : Version of CEDARS used for this project
    Returns:
        None
    """
    proj_info = INFO(project_name = project_name, investigator_name = investigator_name,
                    cedars_version = cedars_version)

    db_session.add(proj_info)
    db_session.commit()

def get_info():
    """
    This function returns the data inside the info table in the sqlalchemy database.
    Note that this table only has one row.

    Args:
        None
    Returns:
        dict : {column name : value}
    """
    proj_info = db_session.query(INFO).first()
    proj_info = row_to_dict(proj_info)

    return proj_info

def get_user(username):
    """
    This function is used to get a user from the database.

    Args:
        username (str) : The name of the user to get.
    Returns:
        user (dict) : The user object from the database.
    """

    user_data = db_session.query(USERS).filter(USERS.user == username).first()

    if user_data is None:
        return None
    
    user_data = row_to_dict(user_data)
    return user_data

def add_user(username, password, is_admin=False):
    """
    This function is used to add a new user to the database.
    All this data is kept in the USERS table.

    Args:
        username (str)  : The name of this user.
        password (str)  : The password this user will need to login to the system.
        is_admin (bool) : True if this user has admin privileges.
    Returns:
        None
    """

   
    new_user = USERS(user = username, password = password, is_admin = is_admin)

    db_session.add(new_user)
    db_session.commit()

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
    db_session.query(QUERY).update({QUERY.current : False})
    # TODO: make a query history and enable multiple queries.


    new_query = QUERY(query = query, tag_query_include = tag_query["include"][0],
                     tag_query_exclude = tag_query["exclude"][0],
                     exclude_negated = exclude_negated, hide_duplicates = hide_duplicates,
                     skip_after_event = skip_after_event, tag_query_exact =  tag_query["exact"][0],
                     tag_query_nlp_apply = tag_query["nlp_apply"][0])

    db_session.add(new_query)
    db_session.commit()
    
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
    query_data = db_session.query(QUERY).filter(QUERY.current == True).first()
    if query_data is None:
        return None
    else:
        return query_data.query



def upload_notes(documents):
    """
    This function is used to take a dataframe of patient records
    and save it to the database.

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
        note_obj = db_session.query(NOTES).filter(NOTES.text_id == note_info["text_id"]).first()
        is_present = (note_obj != None)

        if is_present:
            logging.error("Cancelling duplicate note entry")
        else:
            new_note = NOTES(text_id = note_info["text_id"].replace('"', '""'),
                             text = note_info["text"].replace('"', '""'),
                             patient_id = note_info['patient_id'],
                             text_date = note_info["text_date"],
                             doc_id = note_info["doc_id"].replace('"', '""'),
                             text_sequence = note_info["text_sequence"],
                             text_tag_1 = note_info["text_tag_1"].replace('"', '""'),
                             text_tag_2 = note_info["text_tag_2"].replace('"', '""'),
                             text_tag_3 = note_info["text_tag_3"].replace('"', '""'),
                             text_tag_4 = note_info["text_tag_4"].replace('"', '""'))
            db_session.add(new_note)

            patient_ids.add(note_info["patient_id"])

    for p_id in patient_ids:
         # check if patient already exists in database
        patient_obj = db_session.query(PATIENTS).filter(PATIENTS.patient_id == p_id).first()
        is_present = (patient_obj != None)
        
        if not is_present:
            new_patient = PATIENTS(patient_id = p_id, reviewed = False,
                                   locked = False, updated = False,
                                   admin_locked = False)
            db_session.add(new_patient)
    
    db_session.commit()

def  get_all_annotations_for_note(note_id):
    """
    This function is used to get all the annotations for a particular note.
    """
    anno_query = db_session.query(ANNOTATIONS).filter(ANNOTATIONS.note_id == note_id)
    anno_data = anno_query.order_by(ANNOTATIONS.note_start_index).all()

    annotations = []
    for row in anno_data:
        row = row_to_dict(row)
        annotations.append(row.copy())

    return annotations


def get_annotation(annotation_id):
    """
    Retrives annotation from database.

    Args:
        annotation_id (str) : Unique ID for the annotation.
    Returns:
        annotation (dict) : Dictionary for an annotation from database.
            The keys are the attribute names.
            The values are the values of the attribute in that record.
    """

    anno_query = db_session.query(ANNOTATIONS).filter(ANNOTATIONS.anno_id == annotation_id)
    anno_data = anno_query.first()

    anno_data = row_to_dict(anno_data)

    return anno_data

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
  
    anno_query = db_session.query(ANNOTATIONS).filter(ANNOTATIONS.anno_id == annotation_id)
    note_id = anno_query.first().note_id
    note_data = db_session.query(NOTES).filter(NOTES.text_id == note_id)

    
    note_data = note_data.first()

    note_info = row_to_dict(note_data)

    return note_info


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
    
    patient_query = db_session.query(PATIENTS).filter(and_(PATIENTS.reviewed == False,
                                                           PATIENTS.locked == False))
    
    patient_data = patient_query.first()

    if patient_data is None:
        logging.debug("Failed to retrive any further un-reviewed patients from the database.")
        return None

    logging.debug("Retriving patient #%s from database.", patient_data.patient_id)
    return patient_data.patient_id


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

    anno_query = db_session.query(ANNOTATIONS).filter(and_(ANNOTATIONS.patient_id == p_id,
                                                              ANNOTATIONS.reviewed == False,
                                                              ANNOTATIONS.isNegated == False))
    
    annotation_data = anno_query.all()

    return [str(row.anno_id) for row in annotation_data]

def mark_annotation_reviewed(annotation_id):
    """
    Updates the annotation in the database to mark it as reviewed.

    Args:
        annotation_id (str) : Unique ID for the annotation.
    Returns:
        None
    """
    logging.debug("Marking annotation #%s as reviewed.", annotation_id)

    annotation = db_session.query(ANNOTATIONS).filter(ANNOTATIONS.anno_id == annotation_id)
    annotation.update({ANNOTATIONS.reviewed : True})

    db_session.commit()

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

    annotation = db_session.query(ANNOTATIONS).filter(ANNOTATIONS.anno_id == annotation_id)

    # convert date to datetime object
    if new_date is not None:
        new_date = datetime.strptime(new_date, "%Y-%m-%d")
        annotation.update({ANNOTATIONS.event_date : new_date})
    else:
        annotation.update({ANNOTATIONS.event_date : None})

    db_session.commit()

def delete_annotation_date(annotation_id):
    """
    Deletes the event date for an annotation.

    Args:
        annotation_id (str) : Unique ID for the annotation.
    Returns:
        None
    """
    logging.debug("Deleting date on annotation #%s.", annotation_id)

    annotation = db_session.query(ANNOTATIONS).filter(ANNOTATIONS.anno_id == annotation_id)
    annotation.update({ANNOTATIONS.event_date : None})
    
    db_session.commit()

def get_annotation_date(annotation_id):
    """
    Retrives the event date for an annotation.
    """
    logging.debug("Retriving date on annotation #%s.", annotation_id)

    annotation = db_session.query(ANNOTATIONS).filter(ANNOTATIONS.anno_id == annotation_id)
    annotation_data = annotation.first()
    
    if annotation_data is None:
        return None
    
    return annotation_data.event_date


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

    patient = db_session.query(PATIENTS).filter(PATIENTS.patient_id == patient_id)
    patient.update({PATIENTS.reviewed : is_reviewed})
    
    db_session.commit()

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

    new_comment = COMMENTS(anno_id = annotation_id, comment = comment)
    db_session.add(new_comment)
    
    db_session.commit()

def empty_annotations():
    """
    Deletes all annotations from the database.
    """

    logging.info("Deleting all data in annotations collection.")
    db_session.query(ANNOTATIONS).delete()
    db_session.commit()

def get_all_annotations():
    """
    Returns a list of all annotations from the database.

    Args:
        None
    Returns:
        Annotations (list) : This is a list of all annotations from the database.
    """

    anno_data = db_session.query(ANNOTATIONS).all()

    return [row_to_dict(row) for row in anno_data]


def get_comments(annotation_id):
    anno_comments = db_session.query(COMMENTS).filter(COMMENTS.anno_id == annotation_id).all()

    return [row.comment for row in anno_comments] # select the first column only

def get_proj_name():
    """
    Returns the name of the current project.

    Args:
        None
    Returns:
        proj_name (str) : The name of the current CEDARS project.
    """

    data = db_session.query(INFO).first()
    
    if data is None:
        return None
    
    return data.project_name

def update_project_name(new_name):
    """
    Updates the project name in the INFO collection of the database.

    Args:
        new_name (str) : New name of the project.
    Returns:
        None
    """
    logging.debug("Updating project name to #%s.", new_name)

    db_session.query(INFO).update({INFO.project_name : new_name})
    
    db_session.commit()


def get_curr_version():
    """
    Returns the name of the current project.

    Args:
        None
    Returns:
        proj_name (str) : The name of the current CEDARS project.
    """

    data = db_session.query(INFO).first()
    
    if data is None:
        return None
    
    return data.cedars_version

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

    user_data = db_session.query(USERS).filter(USERS.user == username).first()

    if user_data is None:
        return None

    user_pass = user_data.password

    return check_password_hash(user_pass, password)

def get_project_users():
    """
    Returns all the usernames for approved users (including the admin) for this project

    Args:
        None
    Returns:
        usernames (list) : List of all usernames for approved users
                           (including the admin) for this project
    """

    users = db_session.query(USERS).all()

    return [user.user for user in users]


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

    annotations = db_session.query(ANNOTATIONS).filter(ANNOTATIONS.isNegated == False).all()

    unique_patients = {annotation.patient_id for annotation in annotations}

    stats["number_of_annotated_patients"] = len(unique_patients)

    num_reviewed_annotations = 0

    for p_id in unique_patients:
        patient_annos_reviewed = db_session.query(ANNOTATIONS).filter(and_(ANNOTATIONS.patient_id == p_id,
                                                                       ANNOTATIONS.reviewed == True))
        anno = patient_annos_reviewed.first()

        is_reviewed = (anno is not None)

        if is_reviewed:
            num_reviewed_annotations += 1

    stats["number_of_reviewed"] = num_reviewed_annotations

    lemma_dist = {}
    for anno in annotations:
        lemma = anno.lemma # get the first column from results
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
    patient_data = db_session.query(PATIENTS).all()

    return [row_to_dict(row) for row in patient_data]

def set_patient_lock_status(patient_id, status):
    """
    Updates the status of the patient to be locked or unlocked.

    Args:
        patient_id (int) : ID for the patient we are locking / unlocking
        status (bool) : True if the patient is being locked, False otherwise.

    Returns:
        None
    """

    patient_query = db_session.query(PATIENTS).filter(PATIENTS.patient_id == patient_id)
    patient_query.update({PATIENTS.locked : status})

    db_session.commit()

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
    patient_data = db_session.query(PATIENTS).filter(PATIENTS.patient_id == patient_id)
    patient_data = patient_data.first()

    if patient_data is None:
        return None

    return patient_data.locked


def get_patient_notes(patient_id):
    """
    Returns all notes for that patient.

    Args:
        patient_id (int) : ID for the patient
    Returns:
        notes (list) : A list of all notes for that patient
    """
    
    note_data = db_session.query(NOTES).filter(NOTES.patient_id == patient_id).all()

    return [row_to_dict(row) for row in note_data]

def insert_one_annotation(annotation):
    """
    Adds an annotation to the database.

    Args:
        annotation (dict) : The annotation we are inserting
    Returns:
        None
    """
    
    new_anno = ANNOTATIONS(note_id = annotation["note_id"].replace('"', '""'),
                           sentence = annotation["sentence"].replace('"', '""'),
                           token = annotation["token"].replace('"', '""'),
                           lemma = annotation["lemma"].replace('"', '""'),
                           isNegated = annotation["isNegated"],
                           start_index = annotation["start_index"],
                           end_index = annotation["end_index"],
                           note_start_index = annotation["note_start_index"],
                           note_end_index = annotation["note_end_index"],
                           sentence_number = annotation["sentence_number"],
                           patient_id = annotation["patient_id"],
                           event_date = annotation["event_date"],
                           reviewed = annotation["reviewed"])

    db_session.add(new_anno)
    db_session.commit()

def remove_all_locked():
    """
    Sets the locked status of all patients to False.
    This is done when the server is shutting down.
    """

    db_session.query(PATIENTS).update({PATIENTS.locked : False})
    db_session.commit()

def is_admin_user(username):
    """check if the user is admin"""
    user = db_session.query(USERS).filter(USERS.user == username).first()

    if user is not None:
        return bool(user.is_admin)
    
    return False

def drop_database(name):
    """Clean Database"""
    os.remove(f"{name}.db")
