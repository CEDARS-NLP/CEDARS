"""
Ensures that the mongodb database is compatible with older CEDARS versions.
"""
import os
from bson import ObjectId
from dotenv import load_dotenv
from .db import mongo
from . import db

load_dotenv()

def update_patient_comments(patient_data):
    '''
    Updates the comments section of the patient's information.
    This data is updated inplace in the dictionary that in entered.

    Args :
        - patient_data (dict) : Dict of the data for that patient in the 
                                    PATIENTS collection.
    
    Returns :
        - None (updates done inplace)
    '''

    # Check if this is a version where comments were added to patients
    if "comments" not in patient_data:
        # In very early CEDARS versions, comments were stored in the annotations collection
        # This will compile and put them in the patient collection if needed
        patient_annotations = db.get_all_annotations_for_patient(patient_data['patient_id'])
        comments = []
        for annotation in patient_annotations:
            if "comments" in annotation:
                comments.extend(annotation["comments"])

        patient_data["comments"] = "\n".join(comments)
    else:
        # This is a version at or after comments were added to
        # the patient collection.
        if isinstance(patient_data["comments"], list):
            patient_data["comments"] = "\n".join(patient_data["comments"])

def update_patient_event_date(patient_data):
    '''
    Updates the event_date and event_annotation_id of the patient.
    This data is updated inplace in the dictionary that in entered.

    Args :
        - patient_data (dict) : Dict of the data for that patient in the 
                                    PATIENTS collection.
    
    Returns :
        - None (updates done inplace)
    '''

    if 'event_date' not in patient_data:
        event_date = None
        event_annotation_id = None
        patient_annotations = db.get_all_annotations_for_patient(patient_data['patient_id'])
        for annotation in patient_annotations:
            if annotation.get("event_date"):
                event_date = annotation.get("event_date")
                event_annotation_id = annotation.get("_id")

        patient_data["event_date"] = event_date
        patient_data["event_annotation_id"] = event_annotation_id

def ensure_patient_compatibility():
    '''
    Checks that the patient collection schema is up to date with the 
    latest version.
    '''

    for patient_id in db.get_all_patient_ids():
        patient_info = db.get_patient_by_id(patient_id)

        update_patient_comments(patient_info)
        update_patient_event_date(patient_info)

        mongo.db["PATIENTS"].update_one({"patient_id" : patient_id},
                                       { "$set": {
                                           "event_date" : patient_info["event_date"],
                                           "event_annotation_id" : patient_info["event_annotation_id"],
                                           "comments" : patient_info["comments"] } })

def ensure_annotation_compatibility():
    '''
    Checks that the annotations collection schema is up to date with the 
    latest version.
    '''

    for annotation in db.get_all_annotations():
        # We only need to ensure that sentence_start is present
        if 'sentence_start' in annotation:
            continue

        note = db.get_annotation_note(str(annotation["_id"]))
        full_text = note["text"].lower()
        sentence = annotation["sentence"].lower()

        mongo.db["ANNOTATIONS"].update_one({"_id" : ObjectId(str(annotation["_id"]))},
                                       { "$set": { "sentence_start" : full_text.index(sentence) }})

def ensure_info_compatibility():
    '''
    Checks that the info collection schema is up to date with the 
    latest version.
    '''

    info_data = db.get_info()
    if 'is_pines_server_enabled' not in info_data:
        mongo.db["INFO"].update_one({"_id" : ObjectId(str(info_data["_id"]))},
                                       { "$set": { "is_pines_server_enabled" : False }})

    if 'pines_url' not in info_data:
        pines_url = os.getenv("PINES_API_URL")
        if pines_url is None:
            pines_url = ""

        mongo.db["INFO"].update_one({"_id" : ObjectId(str(info_data["_id"]))},
                                       { "$set": { "pines_url" : pines_url }})

def ensure_pines_compatibility():
    '''
    Checks that the PINES collection schema is up to date with the 
    latest version.
    '''

    for pines_info in mongo.db["PINES"].find({}):
        if "text_date" in pines_info:
            continue

        note_data = mongo.db["NOTES"].find({'text_id' : pines_info['text_id']})
        text_date = note_data["text_date"]

        mongo.db["PINES"].update_one({"_id" : ObjectId(str(pines_info["_id"]))},
                                       { "$set": { "text_date" : text_date }})



def update_db_schema():
    '''
    Performs updates to ensure compatibility on
    all relevant databases.
    '''
    ensure_patient_compatibility()
    ensure_annotation_compatibility()
    ensure_info_compatibility()
    ensure_pines_compatibility()
