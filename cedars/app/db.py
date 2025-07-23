"""
This file contatins an abstract class for CEDARS to interact with mongodb.
"""

from math import ceil
import os
from io import BytesIO, StringIO
import re
from datetime import datetime
from uuid import uuid4

from typing import Optional
from faker import Faker
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError
import flask
from flask import g
import requests
import pandas as pd
import polars as pl
from werkzeug.security import check_password_hash
from bson import ObjectId
from loguru import logger
from .database import mongo, minio
from .cedars_enums import ReviewStatus
from .cedars_enums import log_function_call


fake = Faker()

logger.enable(__name__)

# Create collections and indexes
@log_function_call
def create_project(project_name,
                   investigator_name,
                   project_id=None,
                   cedars_version="0.1.0"):
    """
    This function creates all the collections in the mongodb database for CEDARS.

    Args:
        project_name (str) : Name of the research project
        investigator_name (str) : Name of the investigator on this project
        cedars_version (str) : Version of CEDARS used for this project
    Returns:
        None
    """
    create_db_indices()
    if mongo.db["INFO"].find_one() is not None:
        logger.info("Database already created.")
        return

    if project_id is None:
        project_id = str(uuid4())

    create_info_col(project_name=project_name,
                    project_id=project_id,
                    investigator_name=investigator_name,
                    cedars_version=cedars_version)

    logger.info("Database creation successful!")

@log_function_call
def create_pines_info(pines_url, is_url_from_api):
    """
    Retrives the PINES url from the relevant source and
        updates the INFO col with the information.
    """
    update_pines_api_url(pines_url)
    update_pines_api_status(is_url_from_api)

    return pines_url

@log_function_call
def create_info_col(project_name,
                    project_id,
                    investigator_name,
                    cedars_version):
    """
    This function creates the info collection in the mongodb database.
    The info collection is used to store meta-data regarding the current project.

    Args:
        project_name (str) : Name of the research project
        investigator_name (str) : Name of the investigator on this project
        cedars_version (str) : Version of CEDARS used for this project
    Returns:
        None
    """
    collection = mongo.db["INFO"]

    info = {"creation_time": datetime.now(),
            "project": project_name,
            "project_id": project_id,
            "investigator": investigator_name,
            "CEDARS_version": cedars_version}

    collection.insert_one(info)
    logger.info("Created INFO collection.")


# index functions
@log_function_call
def create_index(collection, index: list):
    """
    This function is used to create an index in a collection
    Add support for features such as unique=True etc

    Args:
        collection (str) : The name of the collection to create the index in.
        index (str|tuple) : The name of the index to create or a tuple with the name and options.

    """
    for i in index:
        if isinstance(i, tuple):
            mongo.db[collection].create_index(i[0], **i[1])
        else:
            mongo.db[collection].create_index(i)
        logger.info(f"Created index {i} in collection {collection}.")

@log_function_call
def create_annotation_indices():
    '''
    Creates indices for the ANNOTATIONS col in the db.
    This is maintained as a seperate function as this collection
    requires many more indices than the others and it is easier
    to organise all of the commands in one place.
    '''

    logger.info("Creating indexes for ANNOTATIONS.")
    create_index("ANNOTATIONS", ["patient_id", "note_id"])
    mongo.db["ANNOTATIONS"].create_index([("patient_id", 1), ("isNegated", 1),
                                        ("text_date", 1), ("note_id", 1), ("note_start_index", 1) ])
    create_index("ANNOTATIONS", ["patient_id", "text_date", "reviewed"])
    create_index("ANNOTATIONS", ["note_id", "reviewed"])
    create_index("ANNOTATIONS", ["patient_id", "reviewed"])

    # Index for get_all_annotations_for_note
    mongo.db["ANNOTATIONS"].create_index([("note_id", 1), ("isNegated", 1),
                                        ("text_date", 1), ("sentence_number", 1)])
    
    # Index for get_all_annotations_for_sentence
    mongo.db["ANNOTATIONS"].create_index([("note_id", 1), ("isNegated", 1),
                                        ("text_date", 1), ("sentence_number", 1),
                                        ("note_start_index", 1)])

    # Index for get_patient_annotation_ids
    mongo.db["ANNOTATIONS"].create_index([("patient_id", 1), ("isNegated", 1),
                                        ("reviewed", 1), ("sentence_number", 1),
                                        ("note_id", 1), ("text_date", 1)])
    
    # Index for get_annotations_post_event
    mongo.db["ANNOTATIONS"].create_index([("patient_id", 1),
                                        ("reviewed", 1), ("text_date", 1)])

    # Index for get_annotated_notes_for_patient
    mongo.db["ANNOTATIONS"].create_index([("patient_id", 1), ("note_start_index", 1),
                                        ("note_id", 1), ("text_date", 1)])

    # Index for mark_annotation_reviewed (note reviewed lookup query)
    mongo.db["ANNOTATIONS"].create_index([("note_id", 1), ("reviewed", 1)])

@log_function_call
def create_db_indices():
    '''
    Creates indices for all of the cols in the db.
    '''
    logger.info("All tasks completed.")

    logger.info("Creating indexes for NOTES.")
    mongo.db["NOTES"].create_index([("text_id", 1 )], unique=True)
    mongo.db["NOTES"].create_index([("patient_id", 1)])
    mongo.db["NOTES"].create_index([("patient_id", 1), ("text_id", 1)], unique=True)

    logger.info("Creating indexes for PATIENTS.")
    mongo.db["PATIENTS"].create_index([("patient_id", 1)], unique=True)

    create_annotation_indices()

    logger.info("Creating indexes for PINES.")
    create_index("PINES", [("text_id", {"unique": True})])
    create_index("PINES", [("patient_id")])

    logger.info("Creating indexes for USERS.")
    create_index("USERS", [("user", {"unique": True})])

    logger.info("Creating indexes for RESULTS.")
    create_index("RESULTS", [("patient_id", {"unique": True})])

    logger.info("Creating indexes for NOTES_SUMMARY.")
    create_index("NOTES_SUMMARY", [("patient_id")])

    logger.info("Creating indexes for USERS.")
    create_index("USERS", [("user", {"unique": True})])

    logger.info("Creating indexes for TASK.")
    create_index("TASK", [("job_id", {"unique": True})])

# Insert functions
@log_function_call
def add_user(username, password, is_admin=False):
    """
    This function is used to add a new user to the database.
    All this data is kept in the USERS collection.

    Args:
        username (str) : The name of this user.
        password (str) : The password this user will need to login to the system.
    Returns:
        None
    """
    info = {
        "user": username,
        "password": password,
        "is_admin": is_admin,
        "date_created": datetime.now()
    }
    mongo.db["USERS"].insert_one(info)
    logger.info(f"Added user {username} to database.")

@log_function_call
def save_query(query, exclude_negated, hide_duplicates,  # pylint: disable=R0913
               skip_after_event, tag_query, date_min=datetime.now(),
               date_max=datetime.now()):

    """
    This function is used to save a regex query to the database.
    All this data is kept in the QUERY collection.

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
        Status (bool) : True if the query was saved,
                        False if query same quqery already exists.
    """
    info = {
        "query": query,
        "exclude_negated": exclude_negated,
        "hide_duplicates": hide_duplicates,
        "skip_after_event": skip_after_event,
        "tag_query": tag_query,
        "date_min": date_min,
        "date_max": date_max
    }

    collection = mongo.db["QUERY"]
    # only one query is current at a time.
    # TODO: make a query history and enable multiple queries.
    info["current"] = True

    if (query == get_search_query() and
            skip_after_event == get_search_query("skip_after_event") and
            tag_query.get('nlp_apply', False) == get_search_query("tag_query").get('nlp_apply', False)):
        logger.info(f"Query already saved : {query}.")
        return False

    collection.update_one({"current": True}, {"$set": {"current": False}})
    collection.insert_one(info)

    logger.info(f"Saved query : {query}.")
    return True

@log_function_call
def update_notes_summary():
    """
    Aggregates note summaries from the NOTES collection and saves them
    to the NOTES_SUMMARY collection.

    Returns:
        int: Number of summaries updated.
    """
    notes_collection = mongo.db["NOTES"]
    notes_summary_collection = mongo.db["NOTES_SUMMARY"]

    # Aggregation pipeline to compute summaries
    pipeline = [
        {
            "$group": {
                "_id": "$patient_id",  # Group by patient_id
                "num_notes": {"$sum": 1},
                "first_note_date": {"$min": "$text_date"},
                "last_note_date": {"$max": "$text_date"}
            }
        },
        {
            "$project": {
                "patient_id": "$_id",
                "num_notes": 1,
                "first_note_date": 1,
                "last_note_date": 1,
                "_id": 0  # Exclude the internal _id field
            }
        }
    ]

    # Perform aggregation
    aggregated_results = list(notes_collection.aggregate(pipeline))

    # Insert or update summaries in NOTES_SUMMARY
    bulk_operations = []
    for summary in aggregated_results:
        bulk_operations.append(
            UpdateOne(
                {"patient_id": summary["patient_id"]},
                {
                    "$set": {
                        "num_notes": summary["num_notes"],
                        "first_note_date": summary["first_note_date"],
                        "last_note_date": summary["last_note_date"],
                    }
                },
                upsert=True
            )
        )

    if bulk_operations:
        # Perform bulk write to update or insert summaries
        result = notes_summary_collection.bulk_write(bulk_operations)
        return result.modified_count + result.upserted_count
    
    return 0

@log_function_call
def bulk_insert_notes(notes):
    notes_collection = mongo.db["NOTES"]
    try:
        result = notes_collection.insert_many(notes)
        logger.info(f"Inserted {len(result.inserted_ids)} notes.")
        return len(result.inserted_ids)
    except BulkWriteError as bwe:
        logger.error(f"Bulk write error: {bwe.details}")
        return bwe.details['nInserted']

@log_function_call
def bulk_upsert_patients(patient_ids):
    '''
    This function will automatically create default enteries in the
    PATIENTS and RESULTS collection for each patient. The order in which
    the patients are uploaded will be maintained using an index_no field.

    For compatibility with older versions of CEDARS without the index_no field,
    mongodb will ignore the sorting step and the program will continue as normal.

    Args :
        - patient_ids (list[str]) : List of all uploaded patient IDs in order.
    
    Returns :
        - total patients and results uploaded
    '''
    patients_collection = mongo.db["PATIENTS"]
    results_collection = mongo.db["RESULTS"]
    patient_operations = []
    results_operations = []
    number_of_patients_in_db = patients_collection.count_documents({})

    # get cached note summary for all patients where each patient is a key
    notes_summary_dict = get_notes_summary()


    for index_no, p_id in enumerate(patient_ids):
        # Update the index in cases where a batch of patients
        # has been added after the initial batch.

        index_no += number_of_patients_in_db
        p_id = str(p_id).strip()

        patient_op = generate_patient_entry(p_id, index_no)
        patient_operations.append(patient_op)

        results_op = generate_results_entry(p_id, index_no, 
                                            first_note_date=notes_summary_dict.get(p_id, {}).get("first_note_date"),
                                            last_note_date=notes_summary_dict.get(p_id, {}).get("last_note_date"),
                                            num_notes=notes_summary_dict.get(p_id, {}).get("num_notes"))
        results_operations.append(results_op)

    try:
        '''
        While we want to maintain the order in which patients are uploaded,
        we ensure this order using the index_no field. For this reason we can
        set ordered=False when performing a bulk write to maintain high speeds
        while maintaining the correct order when showing patients to the user.
        '''
        # bulk write in chunks
        chunk_size = 2000
        total_uploaded_patients = 0
        total_uploaded_results = 0
        for i in range(0, len(patient_operations), chunk_size):
            patients_update = patients_collection.bulk_write(patient_operations[i:i+chunk_size],
                                                            ordered=False)
            total_uploaded_patients += patients_update.upserted_count
    
        for i in range(0, len(results_operations), chunk_size):
            results_update = results_collection.bulk_write(results_operations[i:i+chunk_size],
                                                            ordered=False)
            total_uploaded_results += results_update.upserted_count

        logger.info(f"Inserted {total_uploaded_patients} patients and {total_uploaded_results} results.")
        return total_uploaded_patients, total_uploaded_results
    except BulkWriteError as bwe:
        logger.error(f"Bulk write error: {bwe.details}")

@log_function_call
def generate_patient_entry(p_id: str, index_no: int):
    '''
    Generates a blank entry for a new patient in the PATIENTS collection.

    Args:
        - p_id (str) : Unique ID for the patient.
        - index_no (int) : Order number for this patient.
                            Follows the ordering in which patients are uploaded.

    Returns:
        - operation (pymongo.UpdateOne) : Pymongo operation to insert the patient
                                            into a collection.
    '''

    patient_info = {
        "patient_id": p_id,
        "reviewed": False,
        "locked": False,
        "updated": False,
        "comments": "",
        "reviewed_by": "",
        "event_annotation_id": None,
        "event_date": None,
        "admin_locked": False,
        "index_no" : index_no
    }

    return UpdateOne(
                {"patient_id": p_id},
                {"$setOnInsert": patient_info},
                upsert=True
            )

@log_function_call
def generate_results_entry(p_id: str,
                           index_no: int,
                           first_note_date=None,
                           last_note_date=None,
                           num_notes=None):
    '''
    Generates a blank entry for a new patient in the RESULTS collection.

    Args:
        - p_id (str) : Unique ID for the patient.
        - index_no (int) : Order number for this patient.
                            Follows the ordering in which patients are uploaded.

    Returns:
        - operation (pymongo.UpdateOne) : Pymongo operation to insert the patient
                                            into a collection.
    '''

    first_note_date = get_first_note_date_for_patient(p_id, first_note_date)
    last_note_date = get_last_note_date_for_patient(p_id, last_note_date)
    num_notes = get_num_patient_notes(p_id, num_notes)

    patient_results = {
        'patient_id' : p_id,
        'total_notes' : num_notes,
        'reviewed_notes' : 0,
        'total_sentences' : 0,
        'reviewed_sentences' : 0,
        'sentences' : '',
        'event_date' : None,
        'event_information' : None,
        'first_note_date' : first_note_date,
        'last_note_date' : last_note_date,
        'comments' : '',
        'reviewer' : None,
        'max_score_note_id' : None,
        'max_score_note_date' : None,
        'max_score' : None,
        'predicted_notes' : None,
        'last_updated' : datetime.now(),
        'index_no' : index_no
    }

    return UpdateOne(
                {"patient_id": p_id},
                {"$setOnInsert": patient_results},
                upsert=True
            )

@log_function_call
def insert_one_annotation(annotation):
    """
    Adds an annotation to the database.

    Args:
        annotation (dict) : The annotation we are inserting
    Returns:
        None
    """
    annotations_collection = mongo.db["ANNOTATIONS"]

    annotations_collection.insert_one(annotation)

@log_function_call
def upsert_patient_records(patient_id: str, insert_datetime: datetime = None, updated_by: str = None):
    '''
    Updates records for a patient in the RESULTS collection.

    Args :
        - patient_id (str) : ID of the patient who has been reviewed.

    Returns :
        - None
    '''

    num_reviewed_notes = mongo.db["NOTES"].count_documents({'patient_id' : patient_id,
                                                        'reviewed' : True})
    all_note_details = get_formatted_patient_predictions(patient_id)

    reviewed_sentences = get_patient_annotation_ids(patient_id,
                                                                reviewed=ReviewStatus.REVIEWED,
                                                                key="sentence")
    unreviewed_sentences = get_patient_annotation_ids(patient_id,
                                                        reviewed=ReviewStatus.UNREVIEWED,
                                                        key="sentence")
    sentences = reviewed_sentences + unreviewed_sentences


    event_date = get_event_date(patient_id)
    key_annotation_id = get_event_annotation_id(patient_id)
    event_information = ""
    if event_date and key_annotation_id:
        key_annotation = get_annotation(key_annotation_id)
        event_information = key_annotation["sentence"]
        key_note_id = key_annotation["note_id"]
        event_information += f"\nNote_id : {key_note_id}"

    first_note_date = get_first_note_date_for_patient(patient_id)
    last_note_date = get_last_note_date_for_patient(patient_id)
    patient = get_patient_by_id(patient_id)
    comments = patient.get("comments", "")

    if updated_by is not None:
        reviewer = updated_by
    else:
        reviewer = get_patient_reviewer(patient_id)

    max_score = None
    max_score_note_id = ""
    max_score_note_date = None
    try:
        res = list(get_max_prediction_score(patient_id))
        if len(res) > 0:
            res = res[0]
            max_score = res["max_score"]
            max_score_note_id = res["text_id"]
            max_score_note_date = get_note_date(max_score_note_id)
    except Exception:
        logger.info(f"PINES results not available for patient: {patient_id}")

    patient_results = {
        'patient_id' : patient_id,
        'total_notes' : get_num_patient_notes(patient_id),
        'reviewed_notes' : num_reviewed_notes,
        'total_sentences' : len(sentences),
        'reviewed_sentences' : len(reviewed_sentences),
        'sentences' : "\n".join(sentences),
        'event_date' : event_date,
        'event_information' : event_information,
        'first_note_date' : first_note_date,
        'last_note_date' : last_note_date,
        'comments' : comments,
        'reviewer' : reviewer,
        'max_score_note_id' : max_score_note_id,
        'max_score_note_date' : max_score_note_date,
        'max_score' : max_score,
        'predicted_notes' : all_note_details,
        'last_updated' : insert_datetime,
    }

    logger.info(f"Updating results for patient #{patient_id}.")
    patient_results.pop("patient_id")
    mongo.db["RESULTS"].update_one({"patient_id": patient_id},
                                    {"$set": patient_results})

# Get functions
@log_function_call
def get_user(username):
    """
    This function is used to get a user from the database.

    Args:
        username (str) : The name of the user to get.
    Returns:
        user (dict) : The user object from the database.
    """
    user = mongo.db["USERS"].find_one({"user": username})
    return user

@log_function_call
def get_search_query(query_key="query"):
    """
    This function is used to get the current search query from the database.
    All this data is kept in the QUERY collection.
    """
    query = mongo.db["QUERY"].find_one({"current": True})

    if query:
        return query[query_key]

    return ""

@log_function_call
def get_search_query_details():
    """
    This function is used to get the current search query details
    from the database.
    """
    query = mongo.db["QUERY"].find_one({"current": True})

    if query:
        query.pop("_id")
        return query

    return {}

@log_function_call
def get_info():
    """
    This function returns the info collection in the mongodb database.
    """
    info = mongo.db["INFO"].find_one()

    if info is not None:
        return info

    return {}

@log_function_call
def get_annotation(annotation_id):
    """
    Retrives annotation from mongodb.

    Args:
        annotation_id (str) : Unique ID for the annotation.
    Returns:
        annotation (dict) : Dictionary for an annotation from mongodb.
            The keys are the attribute names.
            The values are the values of the attribute in that record.
    """
    annotation = mongo.db["ANNOTATIONS"].find_one({"_id": ObjectId(annotation_id)})

    return annotation

@log_function_call
def get_annotation_note(annotation_id: str):
    """
    Retrives note linked to a paticular annotation.

    Args:
        annotation_id (str) : Unique ID for the annotation.
    Returns:
        note (dict) : Dictionary for a note from mongodb.
                      The keys are the attribute names.
                      The values are the values of the attribute in that record.
    """
    logger.debug(f"Retriving annotation #{annotation_id} from database.")
    annotation = mongo.db["ANNOTATIONS"].find_one({"_id": ObjectId(annotation_id)})
    if not annotation:
        return None

    note = mongo.db["NOTES"].find_one({"text_id": annotation["note_id"]})

    return note

@log_function_call
def get_patient_by_id(patient_id: str):
    """
    Retrives a single patient from mongodb.

    Args:
        patient_id (int) : Unique ID for a patient.
    Returns:
        patient (dict) : Dictionary for a patient from mongodb.
                         The keys are the attribute names.
                         The values are the values of the attribute in that record.
    """
    logger.debug(f"Retriving patient #{patient_id} from database.")
    patient = mongo.db["PATIENTS"].find_one({"patient_id": patient_id})

    return patient

@log_function_call
def get_patient():
    """
    Retrives a single patient ID who has not yet been reviewed and is not currently locked.
    The chosen patient is the first one in the database that has not yet been reviewed. The
    order in which un-reviewed patients are selected is based on the order in which they were
    uploaded by the user.

    Args:
        None
    Returns:
        patient_id (int) : Unique ID for a patient.
    """

    # todo: make sure it only get patients who have annotations atleast
    # while adjuticating

    # Sort patients by index_no to maintain order of upload
    # mongodb will ignore this command if index_no does not exist.
    # This is improtant for backwards compatibility,
    # as the index_no will not be present in older CEDARS versions.
    patient = mongo.db["PATIENTS"].find({"reviewed": False,
                                             "locked": False}).sort([("index_no", 1)]).limit(1)

    # Extract the first record as we only retrived one patient due to limit(1)
    patient = list(patient)[0]


    if patient is not None and "patient_id" in patient.keys():
        logger.debug(f"Retriving patient #{patient['patient_id']} from database.", )
        return patient["patient_id"]

    logger.info("Failed to retrive any further un-reviewed patients from the database.")
    return None

@log_function_call
def get_patients_to_annotate():
    """
    Retrieves a patient that have not been reviewed

    Args:
        None
    Returns:
        patient_to_annotate: A single patient that needs to manually reviewed
    """
    logger.info("Retriving all un-reviewed patients from database.")

    # check is this patient has any unreviewed annotations
    for patient_id in get_patient_ids():
        annotations = get_patient_annotation_ids(patient_id)
        if len(annotations) > 0:
            return patient_id

    return None

@log_function_call
def patient_results_exist(patient_id: str):
    '''
    Checks if the results for this patient exist in the RESULTS collection.

    Args :
        - patient_id (str) : ID of the patient.

    Returns :
        - has_result (bool) : True if this patient has a stored result.
    '''

    stored_results = mongo.db["RESULTS"].find_one({"patient_id": patient_id})

    if stored_results is None:
        return False
    return True

@log_function_call
def get_formatted_patient_predictions(patient_id: str):
    '''
    Checks if the results for this patient exist in the RESULTS collection.

    Args :
        - patient_id (str) : ID of the patient.

    Returns :
        - concat_patient_predictions (str) : A string with each predicted note
                as well as the prediction scores. 
                Each prediction is in the format {note_id:note_date:prediction_score} .
                Each prediction is seperated by a newline character.
    '''
    match_stage = {'patient_id' : patient_id, "predicted_score":{'$ne':None}}

    group_stage = {
                    '_id' : None,
                    'note_prediction': { '$push': { '$concat': [ "$text_id", ":", 
                    { "$dateToString": { "format": "%Y-%m-%d", "date": "$text_date" } },
                    ":", {'$toString': "$predicted_score"}  ] } }
                    }

    concat_stage = {
                    'concat_patient_predictions': {
                        '$reduce': {
                            'input': "$note_prediction",

                            'initialValue': "",
                            'in': {
                                '$cond': [ { "$eq": [ "$$value", "" ] },
                                "$$this", { '$concat': [ "$$value", "\n", "$$this" ] } ]
                            }
                        }}
                    }

    pipeline = []
    pipeline.append({'$match': match_stage})
    pipeline.append({ '$group' : group_stage})
    pipeline.append({ '$project' : concat_stage})

    result = mongo.db["PINES"].aggregate(pipeline)
    result = list(result)

    if len(result) > 0:
        return result[0]['concat_patient_predictions']

    return None

@log_function_call
def get_documents_to_annotate(patient_id=None):
    """
    Retrives all documents that have not been annotated.

    Returns: All matching notes from the database.
    """
    logger.debug("Retriving all annotated documents from database.")
    match_stage = {
        "annotations": {"$eq": []},
        "reviewed": {"$ne": True}
    }
    if patient_id:
        match_stage["patient_id"] = patient_id

    documents_to_annotate = mongo.db["NOTES"].aggregate(
        [{
            "$lookup": {
                "from": "ANNOTATIONS",
                "localField": "text_id",
                "foreignField": "note_id",
                "as": "annotations"
            }
        }, {
            "$match": match_stage
        }])

    return documents_to_annotate

@log_function_call
def get_all_annotations_for_patient(patient_id: str):
    """
    Retrives all annotations for a patient.

    Args:
        patient_id (str) : Unique ID for a patient.
    Returns:
        annotations (list) : A list of all annotations for that patient.
    """
    annotations = list(mongo.db["ANNOTATIONS"]
                       .find({"patient_id": patient_id, "isNegated": False})
                       .sort([("text_date", 1), ("note_id", 1), ("note_start_index", 1)]))

    return annotations

@log_function_call
def get_patient_annotation_ids(p_id: str, reviewed=ReviewStatus.UNREVIEWED, key="_id"):
    """
    Retrives all annotation IDs for annotations linked to a patient.

    Args:
        p_id (str) : Unique ID for a patient.
        reviewed (ReviewStatus Enum) : The status of the annotation wrt being reviewed.
    Returns:
        annotations (list) : A list of all annotation IDs linked to that patient.
    """
    logger.info(f"Retriving annotations for patient #{p_id} from database.")
    query_filter = {"patient_id": p_id, "isNegated": False, "reviewed": reviewed.value}

    annotation_ids = mongo.db["ANNOTATIONS"].find(
        query_filter).sort([
            ("note_id", 1),
            ('text_date', 1),
            ("sentence_number", 1)])

    res = []
    if key == "sentence":
        for _id in annotation_ids:
            cleaned_sentence = ' '.join(_id[key].split())
            res.append(f'{_id["note_id"]}:{str(_id["text_date"])[:10]}:{cleaned_sentence}')
    else:
        res = [str(_id[key]) for _id in annotation_ids]

    return res

@log_function_call
def get_annotations_post_event(patient_id: str, event_date: datetime.date):
    '''
    Retirves the annotation IDs for unreviewed events on or
    after the event date for a paticular patient.

    Args:
        - patient_id (str) : ID for the patient
        - event_date(Date) : Date on which the event was found
    
    Returns:
        - annotation_ids (list) : List of annotation ID for the unreviewed
                                    annotations on or after that date.
    '''

    a_ids = mongo.db["ANNOTATIONS"].find({ 'patient_id' : patient_id,
                                        'text_date': {'$gte': event_date},
                                        'reviewed': ReviewStatus.UNREVIEWED.value
                                        })

    return [x["_id"] for x in a_ids]

@log_function_call
def get_event_date(patient_id: str):
    """
    Find the event date for a patient.
    """
    logger.debug(f"Retriving event date for patient #{patient_id}.")
    patient = mongo.db["PATIENTS"].find_one({"patient_id": patient_id})

    if patient and patient['event_date'] is not None:
        #date_format = '%Y-%m-%d'
        #event_date = datetime.strptime(patient['event_date'], date_format)
        return patient['event_date']

    return None

@log_function_call
def get_note_date(note_id):
    """
    Retrives the date of a note.

    Args:
        note_id (str) : Unique ID for a note.
    Returns:
        note_date (datetime) : The date of the note.
    """
    logger.debug(f"Retriving date for note #{note_id}.")
    note = mongo.db["NOTES"].find_one({"text_id": note_id})
    return note["text_date"]

@log_function_call
def get_first_note_date_for_patient(patient_id: str, first_note_date=None):
    """
    Retrives the date of the first note for a patient.

    Args:
        patient_id (str) : Unique ID for a patient.
    Returns:
        note_date (datetime) : The date of the first note for the patient.
    """
    logger.debug(f"Retriving first note date for patient #{patient_id}.")

    # pass cached value if available
    if first_note_date is not None:
        return first_note_date
    
    summary = mongo.db["NOTES_SUMMARY"].find_one(
        {"patient_id": patient_id},
        {"_id": 0, "first_note_date": 1}  # Project only the first_note_date field
    )

    if not summary:
        return None
    return summary["first_note_date"]

@log_function_call
def get_notes_summary():
    """
    Returns a dictionary of note summaries for all patients in the project.

    Args:
        None
    Returns:
        notes_summary (dict) : A dictionary of note summaries for all patients.
    """
    notes_summary = mongo.db["NOTES_SUMMARY"].find()

    return {summary["patient_id"]: summary for summary in notes_summary}

@log_function_call
def get_last_note_date_for_patient(patient_id: str, last_note_date=None):
    """
    Retrives the date of the last note for a patient.

    Args:
        patient_id (str) : Unique ID for a patient.
    Returns:
        note_date (datetime) : The date of the last note for the patient.
    """
    logger.debug(f"Retriving first note date for patient #{patient_id}.")
    # pass cached value if available
    if last_note_date is not None:
        return last_note_date
    
    summary = mongo.db["NOTES_SUMMARY"].find_one(
        {"patient_id": patient_id},
        {"_id": 0, "last_note_date": 1}  # Project only the first_note_date field
    )

    if not summary:
        return None
    return summary["last_note_date"]

@log_function_call
def get_all_annotations():
    """
    Returns a list of all annotations from the database.

    Args:
        None
    Returns:
        Annotations (list) : This is a list of all annotations from the database.
    """
    annotations = mongo.db["ANNOTATIONS"].find()

    return list(annotations)

@log_function_call
def get_proj_name():
    """
    Returns the name of the current project.

    Args:
        None
    Returns:
        proj_name (str) : The name of the current CEDARS project.
    """

    proj_info = mongo.db["INFO"].find_one()
    if proj_info is None:
        return None
    proj_name = proj_info["project"]
    return proj_name

@log_function_call
def get_curr_version():
    """
    Returns the name of the current project.

    Args:
        None
    Returns:
        proj_name (str) : The name of the current CEDARS project.
    """

    proj_info = mongo.db["INFO"].find_one()

    return proj_info["CEDARS_version"]

@log_function_call
def get_project_users():
    """
    Returns all the usernames for approved users (including the admin) for this project

    Args:
        None
    Returns:
        usernames (list) : List of all usernames for approved users
                           (including the admin) for this project
    """
    users = mongo.db["USERS"].find({})

    return [user["user"] for user in users]

@log_function_call
def get_all_patient_ids():
    """
    Returns all the patient IDs in this project.
    The patients are returned in the order in which they were uploaded.
 
    Args:
        None
    Returns:
        patients (list) : List of all patients in this project
    """

    # Sort patients by index_no when presenting to the user to keep them in the
    # order in which they were uploaded.
    # Mongodb will ignore this command if index_no does not exist.
    # This is improtant for backwards compatibility,
    # as the index_no will not be present in older CEDARS versions.
    patients = mongo.db["PATIENTS"].find({}, {'patient_id' : 1}).sort([('index_no', 1)])

    return [patient["patient_id"] for patient in patients]

@log_function_call
def get_patient_ids():
    """
    Returns all the patient IDs in this project.
    The patients are returned in the order in which they were uploaded.

    Args:
        None
    Returns:
        patient_ids (list) : List of all patient IDs in this project
    """

    # Sorting patients by index_no to maintain upload order
    # Mongodb will ignore this command if index_no does not exist.
    # This is improtant for backwards compatibility,
    # as the index_no will not be present in older CEDARS versions.
    patients = mongo.db["PATIENTS"].find({"reviewed": False, "locked": False}).sort([('index_no', 1)])

    res = [patient["patient_id"] for patient in patients]
    logger.info(f"Retrived {len(res)} patient IDs from the database.")
    return res

@log_function_call
def get_patient_lock_status(patient_id: str):
    """
    Updates the status of the patient to be locked or unlocked.

    Args:
        patient_id (int) : ID for the patient we are locking / unlocking
    Returns:
        status (bool) : True if the patient is locked, False otherwise.
            If no such patient is found, we return None.

    Raises:
        None
    """
    patient = mongo.db["PATIENTS"].find_one({"patient_id": patient_id})
    return patient["locked"]

@log_function_call
def get_all_notes(patient_id: str):
    """
    Returns all notes for that patient.
    """
    notes = mongo.db["NOTES"].find({"patient_id": patient_id})
    return list(notes)

@log_function_call
def get_num_patient_notes(patient_id: str, num_notes=None):
    """
    Returns all notes for that patient.
    """
    logger.debug(f"Retriving number of notes for patient #{patient_id}.")
    # pass cached value if available
    if num_notes is not None:
        return num_notes
    
    summary = mongo.db["NOTES_SUMMARY"].find_one(
        {"patient_id": patient_id},
        {"_id": 0, "num_notes": 1}  # Project only the num_notes field
    )
    
    # Return the num_notes if available, otherwise return 0
    return summary["num_notes"] if summary else 0

@log_function_call
def get_patient_notes(patient_id: str, reviewed=False):
    """
    Returns all notes for that patient.

    Args:
        patient_id (str) : ID for the patient
    Returns:
        notes: A list of all notes for that patient
    """
    mongodb_search_query = {"patient_id": patient_id, "reviewed": reviewed}
    notes = mongo.db["NOTES"].find(mongodb_search_query)
    return notes

@log_function_call
def get_total_counts(collection_name: str, **kwargs) -> int:
    """
    Returns the total number of documents in a collection.

    Args:
        collection_name (str) : The name of the collection to search.
        **kwargs : Additional arguments to pass to the find
    Returns:
        count (int) : The number of documents in the collection.
    """
    return mongo.db[collection_name].count_documents({**kwargs})

@log_function_call
def get_annotated_notes_for_patient(patient_id: str) -> list[str]:
    """
    For a given patient, list all note_ids which have matching keyword
    annotations

    Args:
        patient_id (int) : The patient_id for which we want to retrieve the
            annotated notes

    Returns:
        notes (list[str]) : List of note_ids for the patient which have
            matching keyword annotations
    """
    annotations = (mongo.db["ANNOTATIONS"]
                   .find({"patient_id": patient_id})
                   .sort([("text_date", 1), ("note_id", 1), ("note_start_index", 1)]))
    notes = []
    for annotation in annotations:
        notes.append(annotation["note_id"])

    return list(dict.fromkeys(notes))


# update functions
@log_function_call
def update_project_name(new_name):
    """
    Updates the project name in the INFO collection of the database.

    Args:
        new_name (str) : New name of the project.
    Returns:
        None
    """
    logger.info(f"Updating project name to #{new_name}")
    mongo.db["INFO"].update_one({}, {"$set": {"project": new_name}})

@log_function_call
def update_pines_api_status(new_status):
    """
    Updates the is_pines_server_enabled in the INFO collection of the database
        to reflect the status of the PINES server.

    Args:
        new_status (bool) : True if the PINES server is running.
    Returns:
        None
    """
    logger.info(f"Setting PINES API status to {new_status}")
    mongo.db["INFO"].update_one({},
                                {"$set": {"is_pines_server_enabled": new_status}})

@log_function_call
def update_pines_api_url(new_url):
    """
    Updates the PINES API url in the INFO collection of the database
        to reflect the address of the PINES server.

    Args:
        new_url (str) : The url of the PINES server's API.
    Returns:
        None
    """
    logger.info(f"Setting PINES API url to {new_url}")
    mongo.db["INFO"].update_one({},
                                {"$set": {"pines_url": new_url}})

@log_function_call
def mark_annotation_reviewed(annotation_id, reviewed_by):
    """
    Updates the annotation in the database to mark it as reviewed.
    Also updates the note it belongs to as reviewed if all annotations that
    belong to it are also reviewed.

    Args:
        - annotation_id (str) : Unique ID for the annotation.
        - reviewed_by (str) : The name of the user who reviewed this annotation.

    Returns:
        None
    """
    logger.debug(f"Marking annotation #{annotation_id} as reviewed.")
    mongo.db["ANNOTATIONS"].update_one({"_id": ObjectId(annotation_id)},
                                       {"$set": {"reviewed": ReviewStatus.REVIEWED.value}})

    annotation_data = get_annotation(annotation_id)
    note_id = annotation_data['note_id']

    # Get the number of unreviewed annotations for the note this annotation belongs to
    num_unreviewed_annos = mongo.db["ANNOTATIONS"].count_documents({'note_id' : note_id,
                                  'reviewed' : ReviewStatus.UNREVIEWED.value})

    if num_unreviewed_annos == 0:
        mark_note_reviewed(note_id, reviewed_by)

@log_function_call
def revert_annotation_reviewed(annotation_id, reviewed_by):
    '''
    Reverts a reviewed annotation to be marked unreviewed in the case
    where the event date for that patient is deleted on the current annotation.

    Args:
        - annotation_id (str) : Unique ID for the annotation.
        - reviewed_by (str) : The name of the user who deleted the event_date.
    
    Returns:
        None
    '''
    logger.debug(f"Marking annotation #{annotation_id} as un-reviewed.")
    mongo.db["ANNOTATIONS"].update_one({"_id": ObjectId(annotation_id)},
                                       {"$set": {"reviewed": ReviewStatus.UNREVIEWED.value}})

    annotation_data = get_annotation(annotation_id)
    note_id = annotation_data['note_id']

    # Mark the note this annotation belongs to as un-reviewed
    revert_note_reviewed(note_id, reviewed_by)

@log_function_call
def revert_note_reviewed(note_id, reviewed_by: str):
    """
    Updates the note's status to un-reviewed in the database.
    This occurs when an event_date for the patient is deleted and
    one of the annotations from this note is then marked un-reviewed.

     Args:
        patient_id (int) : Unique ID for a patient.
        reviewed_by (str) : The name of the user who deleted the event_date
                            causing this note to be marked un-reviewed.
    """
    logger.debug(f"Marking note #{note_id} as un-reviewed.")
    mongo.db["NOTES"].update_one({"text_id": note_id},
                                 {"$set": {"reviewed": False,
                                           "reviewed_by": reviewed_by}})

    note_info = mongo.db["NOTES"].find_one({"text_id": note_id})
    revert_patient_reviewed(note_info['patient_id'], reviewed_by)
    
@log_function_call
def revert_patient_reviewed(patient_id, reviewed_by: str):
    """
    Updates the patient's status to un-reviewed in the database.
    This occurs when an event_date for the patient is deleted and
    one of the annotations from this patient is then marked un-reviewed.

     Args:
        patient_id (int) : Unique ID for a patient.
        reviewed_by (str) : The name of the user who deleted the event_date
                            causing this note to be marked un-reviewed.
    """
    logger.debug(f"Marking patient #{patient_id} as un-reviewed.")
    mongo.db["PATIENTS"].update_one({"patient_id": patient_id},
                                 {"$set": {"reviewed": False,
                                           "reviewed_by": reviewed_by}})

@log_function_call
def mark_annotations_post_event(patient_id: str, event_date: datetime.date):
    '''
    Marks the annotation for unreviewed events on or
    after the event date for a paticular patient as skipped. We
    mark them as skipped as annotations after an event date may be ignorged
    and do not need manual review.

    Args:
        - patient_id (str) : ID for the patient
        - event_date(Date) : Date on which the event was found

    Returns:
        - None
    '''
    logger.info(f"Skipping future annotations for patient {patient_id} after {event_date}.")
    mongo.db["ANNOTATIONS"].update_many({ 'patient_id' : patient_id,
                                          'text_date': {'$gte': event_date},
                                          'reviewed': ReviewStatus.UNREVIEWED.value
                                        },
                                        {"$set": {"reviewed": ReviewStatus.SKIPPED.value}})

@log_function_call
def revert_skipped_annotations(patient_id: str):
    '''
    Reverts the skiped annotations for unreviewed events on or
    after the event date for a paticular patient. This is done in the event of
    a patient's event date being deleted.

    Args:
        - patient_id (str) : ID for the patient

    Returns:
        - None
    '''
    mongo.db["ANNOTATIONS"].update_many({ 'patient_id' : patient_id,
                                          'reviewed': ReviewStatus.SKIPPED.value
                                        },
                                        {"$set": {"reviewed": ReviewStatus.UNREVIEWED.value}})

@log_function_call
def update_event_date(patient_id: str, new_date, annotation_id):
    """
    Enters a new event date for an patient.

    Args:
        patient_id (str) : Unique ID for the patient.
        new_date (Date / Datetime obj) : The new value to update the event date of the patient with.
            Must be in the format YYYY-MM-DD.
        annotation_id (str) : ID for the annotation at which the new_date was marked.
    Returns:
        None
    """
    # TODO: UTC dates
    logger.debug(f"Updating date on patient #{patient_id} to {new_date}.")

    mongo.db["PATIENTS"].update_one({"patient_id": patient_id},
                                       {"$set": {"event_date": new_date}})

    update_event_annotation_id(patient_id, annotation_id)

@log_function_call
def delete_event_date(patient_id: str):
    """
    Deletes the event date for a patient.

    Args:
        patient_id (str) : Unique ID for the patient.
    Returns:
        None
    """
    logger.debug(f"Deleting date on patient #{patient_id}.")

    mongo.db["PATIENTS"].update_one({"patient_id": patient_id},
                                       {"$set": {"event_date": None}})
    delete_event_annotation_id(patient_id)

@log_function_call
def get_event_annotation_id(patient_id: str):
    """
    Retrives the ID for the annotation where 
            the event date for a patient was found.

    Args:
        patient_id (str) : Unique ID for the patient.
    Returns:
        None
    """
    logger.debug(f"Retriving event_annotation_id for patient #{patient_id}.")

    patient = mongo.db["PATIENTS"].find_one({"patient_id": patient_id})

    if patient is not None:
        return patient["event_annotation_id"]

    return None

@log_function_call
def update_event_annotation_id(patient_id: str, annotation_id):
    """
    Updates the ID for the annotation where 
            the event date for a patient was found.

    Args:
        patient_id (str) : Unique ID for the patient.
        annotation_id (str) : ID of the annotation where the
            event date for this patient was entered.
    Returns:
        None
    """
    logger.debug(f"Updating event_annotation_id on patient #{patient_id}.")

    mongo.db["PATIENTS"].update_one({"patient_id": patient_id},
                                       {"$set": {"event_annotation_id": annotation_id}})

@log_function_call
def delete_event_annotation_id(patient_id: str):
    """
    Deletes the ID for the annotation where 
            the event date for a patient was found.

    Args:
        patient_id (str) : Unique ID for the patient.
    Returns:
        None
    """
    logger.debug(f"Deleting event_annotation_id on patient #{patient_id}.")

    mongo.db["PATIENTS"].update_one({"patient_id": patient_id},
                                       {"$set": {"event_annotation_id": None}})

@log_function_call
def mark_patient_reviewed(patient_id: str, reviewed_by: str, is_reviewed=True):
    """
    Updates the patient's status to reviewed in the database.

    Args:
        patient_id (int) : Unique ID for a patient.
        reviewed_by (str) : The name of the user who reviewed the patient.
        is_reviewed (bool) : True if patient's annotations have been reviewed.
    Returns:
        None
    """
    logger.debug(f"Marking patient #{patient_id} as reviewed.")
    mongo.db["PATIENTS"].update_one({"patient_id": patient_id},
                                    {"$set": {"reviewed": is_reviewed,
                                              "reviewed_by": reviewed_by}})

    logger.info(f"Storing results for patient #{patient_id}")
    upsert_patient_records(patient_id, datetime.now())

@log_function_call
def mark_note_reviewed(note_id, reviewed_by: str):
    """
    Updates the note's status to reviewed in the database.

     Args:
        patient_id (int) : Unique ID for a patient.
        reviewed_by (str) : The name of the user who reviewed the note.
    """
    logger.debug(f"Marking note #{note_id} as reviewed.")
    mongo.db["NOTES"].update_one({"text_id": note_id},
                                 {"$set": {"reviewed": True,
                                           "reviewed_by": reviewed_by}})

@log_function_call
def reset_patient_reviewed():
    """
    Update all patients, notes to be un-reviewed.
    """
    mongo.db["PATIENTS"].update_many({},
                                     {"$set": {"reviewed": False,
                                               "reviewed_by": "",
                                               "event_annotation_id": None,
                                               "event_date": None,
                                               "comments": ""}})
    mongo.db["NOTES"].update_many({}, {"$set": {"reviewed": False,
                                                "reviewed_by": ""}})

@log_function_call
def add_comment(annotation_id, comment):
    """
    Stores a new comment for a patient.

    Args:
        annotation_id (str) : Unique ID for the annotation.
        comment (str) : Text of the comment on this annotation.
    Returns:
        None
    """
    comment = comment.strip()
    if len(comment) == 0:
        logger.debug(f"Comment deleted on annotation # {annotation_id}.")
    else:
        logger.info(f"Adding comment to annotation #{annotation_id}")
    patient_id = mongo.db["ANNOTATIONS"].find_one(
        {"_id": ObjectId(annotation_id)})["patient_id"]

    mongo.db["PATIENTS"].update_one({"patient_id": patient_id},
                                    {"$set":
                                     {"comments": comment}
                                     })

@log_function_call
def set_patient_lock_status(patient_id: str, status):
    """
    Updates the status of the patient to be locked or unlocked.

    Args:
        patient_id (int) : ID for the patient we are locking / unlocking
        status (bool) : True if the patient is being locked, False otherwise.

    Returns:
        None
    """
    patients_collection = mongo.db["PATIENTS"]
    patients_collection.update_one({"patient_id": patient_id},
                                   {"$set": {"locked": status}})

@log_function_call
def remove_all_locked():
    """
    Sets the locked status of all patients to False.
    This is done when the server is shutting down.
    """
    patients_collection = mongo.db["PATIENTS"]
    patients_collection.update_many({},
                                    {"$set": {"locked": False}})

@log_function_call
def update_annotation_reviewed(note_id: str) -> int:
    """
    Mark all annotations for a note as reviewed.

    Args:
        note_id (str) : The note_id for which we want to mark all annotations as reviewed.
    Returns:
        count (int) : The number of annotations that were marked as reviewed.
    """
    annotations_collection = mongo.db["ANNOTATIONS"]
    result = annotations_collection.update_many({"note_id": note_id},
                                                {"$set": {"reviewed": ReviewStatus.REVIEWED.value}})
    return result.modified_count


# delete functions
@log_function_call
def empty_annotations():
    """
    Deletes all annotations from the database
    """

    logger.info("Deleting all data in annotations collection.")
    annotations = mongo.db["ANNOTATIONS"]
    annotations.delete_many({})

    # also reset the queue
    flask.current_app.task_queue.empty()
    mongo.db["TASK"].delete_many({})

@log_function_call
def drop_database(name):
    """Clean Database"""
    mongo.cx.drop_database(name)


# utility functions
@log_function_call
def check_password(username, password):
    """
    Checks if the password matches the password of that user from the database.

    Args:
        username (str) : The name of the new user
        password (str) : The password entered by the user.

    Returns:
        (bool) : True if the password matches the password of that user from the database.
    """

    user = mongo.db["USERS"].find_one({"user": username})

    return "password" in user and check_password_hash(user["password"], password)

@log_function_call
def is_admin_user(username):
    """check if the user is admin"""
    user = mongo.db["USERS"].find_one({'user': username})

    if user is not None and user["is_admin"]:
        return True

    return False


# stats functions
@log_function_call
def get_curr_stats():
    """
    Returns basic statistics for the project

    """
    stats = {}
    # Aggregation pipeline to count unique patients
    pipeline_unique_patients = [
        {"$group": {"_id": "$patient_id"}}
    ]
    unique_patients = list(mongo.db.PATIENTS.aggregate(pipeline_unique_patients))
    stats["number_of_patients"] = len(unique_patients)

    pipeline_annotated_patients = [
        {"$match": {"isNegated": False}},
        {"$group": {"_id": "$patient_id"}}
    ]
    annotated_patients = list(mongo.db.ANNOTATIONS.aggregate(pipeline_annotated_patients))
    stats["number_of_annotated_patients"] = len(annotated_patients)

    # Aggregation pipeline to count reviewed annotations
    pipeline_reviewed = [
        {"$match": {"reviewed": True}},
        {"$group": {"_id": "$patient_id"}}
    ]
    reviewed_annotations = list(mongo.db.PATIENTS.aggregate(pipeline_reviewed))
    stats["number_of_reviewed"] = len(reviewed_annotations)

    # pipeline for notes and reviewed by user for notes with reviewed_by field
    pipeline_patients = [
        {"$match": {"reviewed": True}},
        {"$group": {"_id": "$reviewed_by", "count": {"$sum": 1}}}
    ]

    reviewed_notes = list(mongo.db.PATIENTS.aggregate(pipeline_patients))
    stats["user_review_stats"] = {doc["_id"]: doc["count"] for doc in reviewed_notes}
    # Aggregation pipeline for lemma distribution
    pipeline_lemma_dist = [
        {"$match": {"isNegated": False}},
        {"$group": {"_id": "$token", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
        {"$project": {"token": "$_id", "_id": 0, "count": 1}}
    ]
    lemma_dist_results = mongo.db.ANNOTATIONS.aggregate(pipeline_lemma_dist)
    total_tokens = mongo.db.ANNOTATIONS.count_documents({"isNegated": False})
    stats['lemma_dist'] = {doc['token']: 100 * doc['count']/total_tokens for doc in lemma_dist_results}

    return stats


# pines functions
@log_function_call
def get_prediction(note: str) -> float:
    """
    ##### PINES predictions

    Get prediction from endpoint. Text goes in the POST request.
    """

    pines_api_url = get_pines_url()

    url = f'{pines_api_url}/predict'
    data = {'text': note}
    log_notes = None
    try:
        response = requests.post(url, json=data, timeout=3600)
        response.raise_for_status()
        res = response.json()["prediction"]
        score = res.get("score")
        label = res.get("label")
        if isinstance(label, str):
            score = 1 - score if "0" in label else score
        else:
            score = 1 - score if label == 0 else score
        log_notes = re.sub(r'\d', '*', note[:20])
        logger.debug(f"Got prediction for note: {log_notes} with score: {score} and label: {label}")
        return score
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get prediction for note: {log_notes}")
        raise e

@log_function_call
def get_max_prediction_score(patient_id: str):
    """
    Get the max predicted note score for a patient
    """
    return mongo.db.PINES.aggregate(
        [
            {
                '$match': {
                    'patient_id': patient_id
                }
            }, {
                '$group': {
                    '_id': '$patient_id',
                    'max_score': {
                        '$max': '$predicted_score'
                    }
                }
            }, {
                '$lookup': {
                    'from': 'PINES',
                    'let': {
                        'patient_id': '$_id',
                        'max_score': '$max_score'
                    },
                    'pipeline': [
                        {
                            '$match': {
                                '$expr': {
                                    '$and': [
                                        {
                                            '$eq': [
                                                '$patient_id', '$$patient_id'
                                            ]
                                        }, {
                                            '$eq': [
                                                '$predicted_score', '$$max_score'
                                            ]
                                        }
                                    ]
                                }
                            }
                        }, {
                            '$project': {
                                'text_id': 1,
                                '_id': 0
                            }
                        }
                    ],
                    'as': 'max_score_texts'
                }
            }, {
                '$addFields': {
                    'text_id': {
                        '$arrayElemAt': [
                            '$max_score_texts.text_id', 0
                        ]
                    }
                }
            }, {
                '$project': {
                    '_id': 1,
                    'max_score': 1,
                    'text_id': 1
                }
            }
        ]
    )

@log_function_call
def get_note_prediction_from_db(note_id: str,
                                pines_collection_name: str = "PINES") -> Optional[float]:
    """
    Retrieve the prediction score for a given from the database

    Args:
        pines_collection_name (str): The name of the collection in the database
        note_id (str): The note_id for which we want to retrieve the prediction

    Returns:
        float: The prediction score for the note
    """
    pines_collection = mongo.db[pines_collection_name]
    query = {"text_id": note_id}

    pines_pred = pines_collection.find_one(query)
    if pines_pred:
        logger.debug(f"Found prediction in db for : {note_id}: {pines_pred.get('predicted_score')}")
        return round(pines_pred.get("predicted_score"), 2)
    logger.debug(f"Prediction not found in db for : {note_id}")
    return None

@log_function_call
def predict_and_save(text_ids: Optional[list[str]] = None,
                     note_collection_name: str = "NOTES",
                     pines_collection_name: str = "PINES",
                     force_update: bool = False) -> None:
    """
    ##### Save PINES predictions

    Predict and save the predictions for the given text_ids.
    """
    notes_collection = mongo.db[note_collection_name]
    pines_collection = mongo.db[pines_collection_name]
    query = {}
    if text_ids is not None:
        query = {"text_id": {"$in": text_ids}}

    cedars_notes = notes_collection.find(query)
    count = 0
    for note in cedars_notes:
        note_id = note.get("text_id")
        if force_update or get_note_prediction_from_db(note_id, pines_collection_name) is None:
            logger.info(f"Predicting for note: {note_id}")
            prediction = get_prediction(note.get("text"))
            pines_collection.insert_one({
                "text_id": note_id,
                "text": note.get("text"),
                "text_date" : note.get("text_date"),
                "patient_id": note.get("patient_id"),
                "predicted_score": prediction,
                "report_type": note.get("text_tag_3"),
                "document_type": note.get("text_tag_1")
                })
        count += 1

@log_function_call
def add_task(task):
    """
    Launch a task and add it to Mongo if it doesn't already exist.
    # TODO: insert only one
    """
    task_db = mongo.db["TASK"]
    task_db.insert_one(task)

@log_function_call
def get_tasks_in_progress():
    """
    Returns tasks that have not been completed yet.
    """
    task_db = mongo.db["TASK"]
    return task_db.find({"complete": False})

@log_function_call
def get_task_in_progress(task_id):
    """
    Returns the task with this ID, if it has not been completed.
    """
    task_db = mongo.db["TASK"]
    return task_db.find_one({"job_id": task_id,
                             "complete": False})

@log_function_call
def get_task(task_id):
    """
    Returns the task with this ID, regardless of it's completion status.
    """
    task_db = mongo.db["TASK"]
    return task_db.find_one({"job_id": task_id})

@log_function_call
def update_db_task_progress(task_id, progress):
    """
    Updates the progress of a task and checks if it has completed.
    This function will also automatically unlock the patient after completion.
    """
    task_db = mongo.db["TASK"]
    task = task_db.find_one({"job_id": task_id})
    completed = False
    if not task:
        # this might be the case if we have old messages
        # in the queue
        logger.error(f"Task {task_id} not found in database.")
        return
    if progress >= 100:
        completed = True
    task_db.update_one({"job_id": task["job_id"]},
                       {"$set": {"progress": progress,
                                 "complete": completed}})
    patient_id = (task_id.split(":")[1]).strip()
    # TODO: handle failed patients?
    set_patient_lock_status(patient_id, False)

@log_function_call
def report_success(job):
    """
    Saves the data associated with a successful job after completion.
    This will also automatically check for the completion of all current tasks.
    If the tasks are completed will then create all required indices and shutdown
    the PINES server if it is running via a SUPERBIO api.
    """
    job.meta['progress'] = 100
    job.save_meta()

    update_db_task_progress(job.get_id(), 100)

@log_function_call
def report_failure(job):
    """
    Saves the data associated with a job that failed to complete.
    This will also automatically check for the completion of all current tasks.
    If the tasks are completed will then create all required indices and shutdown
    the PINES server if it is running via a SUPERBIO api.
    """
    job.meta['progress'] = 0
    job.save_meta()
    update_db_task_progress(job.get_id(), 0)

@log_function_call
def get_patient_reviewer(patient_id: str):
    """
    Updates the note's status to reviewed in the database.
    """

    reviewed_by = mongo.db["PATIENTS"].find_one({"patient_id": patient_id})["reviewed_by"]
    if reviewed_by.strip() == "":
        return None

    return reviewed_by

@log_function_call
def get_pines_url():
    '''
    Retrives PINES url from INFO col.
    '''

    info_col = mongo.db["INFO"].find_one()
    if info_col:
        return info_col["pines_url"]

    return None

@log_function_call
def is_pines_api_running():
    '''
    Returns True if a SuperBIO PINES API server is running.
    '''

    info_col = mongo.db["INFO"].find_one()
    if info_col:
        return info_col["is_pines_server_enabled"]

    return False

@log_function_call
def download_annotations(filename: str = "annotations.csv", get_sentences: bool = False) -> bool:
    """
    Download annotations from the database and stream them to MinIO.
    """
    schema = {
        'patient_id': pl.Utf8,
        'total_notes': pl.Int64,
        'reviewed_notes': pl.Int64,
        'total_sentences': pl.Int64,
        'reviewed_sentences': pl.Int64,
        'sentences': pl.Utf8,
        'event_date': pl.Datetime,
        'event_information': pl.Utf8,
        'first_note_date': pl.Datetime,
        'last_note_date': pl.Datetime,
        'comments': pl.Utf8,
        'reviewer': pl.Utf8,
        'max_score_note_id': pl.Utf8,
        'max_score_note_date': pl.Datetime,
        'max_score': pl.Float64,
        'predicted_notes': pl.Utf8,
        'last_updated' : pl.Datetime
    }

    if  get_sentences is False:
        schema.pop('sentences')

    try:
        logger.info("Starting download task")
        # Create an in-memory buffer for the CSV data
        csv_buffer = StringIO()
        writer = pd.DataFrame(columns=list(schema.keys()))
        writer.to_csv(csv_buffer, index=False, header=True, encoding="utf-8-sig")

        # Write data in chunks and stream to MinIO
        columns_to_retrive = {'_id': False}
        columns_to_retrive.update({column : True for column in schema.keys()})

        # Sorting results by index_no to maintain upload order
        # Mongodb will ignore this command if index_no does not exist.
        # This is improtant for backwards compatibility,
        # as the index_no will not be present in older CEDARS versions.
        logger.info("Retriving RESULTS from db")
        project_results = mongo.db["RESULTS"].find({},
                                                    columns_to_retrive).sort([("index_no", 1)])

        logger.info("Creating dataframe for RESULTS")
        df = pl.DataFrame(project_results, orient="row",
                                           schema=schema,
                                           infer_schema_length=None)

        date_cols = ['first_note_date', 'last_note_date', 'event_date']
        for col in date_cols:
            df = df.with_columns(
                pl.col(col).dt.date().alias(col)
            )

        logger.info("Uploading results to csv buffer")
        chunk_size = 1000
        for chunk_index in range(0, df.shape[0], chunk_size):
            chunk = df.slice(chunk_index, chunk_size)
            logger.info(f"Sending chunk {ceil(chunk_index/chunk_size)+1}/{ceil(df.shape[0]/chunk_size)} to csv buffer")
            csv_buffer.write(chunk.to_pandas().to_csv(header=False,index=False))

        # Move the cursor to the beginning of the buffer
        csv_buffer.seek(0)
        data_bytes = csv_buffer.getvalue().encode('utf-8')
        data_stream = BytesIO(data_bytes)

        logger.info("Uploading RESULTS to minio")
        # Upload to MinIO
        minio.put_object(g.bucket_name,
                         f"annotated_files/{filename}",
                         data_stream,
                         length=len(data_bytes),
                         content_type="application/csv")
        logger.info(f"Uploaded annotations to s3: {filename}")
        return True
    except Exception as e:
        logger.error(f"Failed to upload annotations to s3: {filename}, error: {str(e)}")
        return False

@log_function_call
def update_patient_results(update_existing_results = False):
    '''
    Creates the results collection if it does not exist and
    inserts data for patients that do not have any.
    Optionally updates the data for all patients including
    patients which already have results stored.

    Args :
        - update_existing_results (bool) : True if data for patients
                                            that already have results must
                                            be updated.
    
    Returns :
        - None
    '''

    if "RESULTS" not in mongo.db.list_collection_names():
        # Create results collection
        populate_results()

    for patient_id in get_all_patient_ids():
        if update_existing_results or (not patient_results_exist(patient_id)):
            upsert_patient_records(patient_id)

@log_function_call
def terminate_project():
    """
    ##### Terminate the Project

    Reset the database to the initial state.
    """
    logger.info("Terminating project.")
    # Delete all mongo DB collections
    mongo.db.drop_collection("ANNOTATIONS")
    mongo.db.drop_collection("NOTES")
    mongo.db.drop_collection("PATIENTS")
    mongo.db.drop_collection("USERS")
    mongo.db.drop_collection("QUERY")
    mongo.db.drop_collection("PINES")
    mongo.db.drop_collection("TASK")
    mongo.db.drop_collection("RESULTS")
    mongo.db.drop_collection("NOTES_SUMMARY")

    project_id = os.getenv("PROJECT_ID", None)

    create_project(project_name=fake.slug(),
                   investigator_name=fake.name(),
                   project_id = project_id)
