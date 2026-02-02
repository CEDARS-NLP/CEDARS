"""
Ensures that the mongodb database is compatible with older CEDARS versions.
"""

from pymongo import MongoClient
from tqdm import tqdm
from bson.objectid import ObjectId  

PINES_URL="http://pines:8036"
DB_NAME="cedars"
DB_PORT="27018"
DB_USER="admin"
DB_PWD="password"
DB_HOSTNAME = "127.0.0.1"
client = MongoClient(f"mongodb://{DB_USER}:{DB_PWD}@{DB_HOSTNAME}:{DB_PORT}")
db = client[DB_NAME]

DRY_RUN = True

def get_info():
    """
    This function returns the info collection in the mongodb database.
    """
    info = db["INFO"].find_one()

    if info is not None:
        return info

    return {}

def get_patient_ids():
    """
    Returns all the patient IDs in this project

    Args:
        None
    Returns:
        patient_ids (list) : List of all patient IDs in this project
    """
    patients = db["PATIENTS"].find()
    res = [patient["patient_id"] for patient in patients]
    print(f"Retrived {len(res)} patient IDs from the database.")
    return res

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
    patient = db["PATIENTS"].find_one({"patient_id": patient_id})

    return patient

def get_all_annotations_for_patient(patient_id: str):
    """
    Retrives all annotations for a patient.

    Args:
        patient_id (str) : Unique ID for a patient.
    Returns:
        annotations (list) : A list of all annotations for that patient.
    """
    annotations = list(db["ANNOTATIONS"]
                       .find({"patient_id": patient_id, "isNegated": False})
                       .sort([("text_date", 1), ("note_id", 1), ("note_start_index", 1)]))

    return annotations

def get_all_annotations():
    """
    Returns a list of all annotations from the database.

    Args:
        None
    Returns:
        Annotations (list) : This is a list of all annotations from the database.
    """
    annotations = db["ANNOTATIONS"].find()

    return list(annotations)

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
    annotation = db["ANNOTATIONS"].find_one({"_id": ObjectId(annotation_id)})
    if not annotation:
        return None

    note = db["NOTES"].find_one({"text_id": annotation["note_id"]})

    return note

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
        patient_annotations = get_all_annotations_for_patient(patient_data['patient_id'])
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
        patient_annotations = get_all_annotations_for_patient(patient_data['patient_id'])
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

    print("Checking PATIENT collection.", flush=True)

    for patient_id in tqdm(get_patient_ids()):
        patient_info = get_patient_by_id(patient_id)

        update_patient_comments(patient_info)
        update_patient_event_date(patient_info)

        res = {
            "patient_id": patient_id,
            "$set": {
                "event_date": patient_info["event_date"],
                "event_annotation_id": patient_info["event_annotation_id"],
                "comments": patient_info["comments"]
            }
        }

        if DRY_RUN:
            print(f"Would have updated patient {patient_id} with \n{res}")
            return
        
        db["PATIENTS"].update_one(res)

def ensure_annotation_compatibility():
    '''
    Checks that the annotations collection schema is up to date with the 
    latest version.
    '''

    print("Checking ANNOTATIONS collection.")

    for annotation in tqdm(get_all_annotations()):
        # We only need to ensure that sentence_start is present
        if 'sentence_start' in annotation:
            continue

        note = get_annotation_note(str(annotation["_id"]))
        full_text = note["text"].lower()
        sentence = annotation["sentence"].lower()

        start_index = full_text.index(sentence)
        end_index = start_index + len(sentence)
        res = {
            "_id": ObjectId(str(annotation["_id"])),
            "$set": {
                "sentence_start": start_index,
                "sentence_end": end_index
            }
        }

        if DRY_RUN:
            print(f"Would have updated annotation {annotation['_id']} with \n{res}")
            return
        db["ANNOTATIONS"].update_one(res)


def ensure_info_compatibility(pines_url=""):
    '''
    Checks that the info collection schema is up to date with the 
    latest version.
    '''

    print("Checking INFO collection.")

    info_data = get_info()
    if 'is_pines_server_enabled' not in info_data:
        db["INFO"].update_one({"_id" : ObjectId(str(info_data["_id"]))},
                                       { "$set": { "is_pines_server_enabled" : False }})

    if 'pines_url' not in info_data:
        db["INFO"].update_one({"_id" : ObjectId(str(info_data["_id"]))},
                                       { "$set": { "pines_url" : pines_url }})

def ensure_pines_compatibility():
    '''
    Checks that the PINES collection schema is up to date with the 
    latest version.
    '''

    print("Checking PINES collection.")

    for pines_info in tqdm(list(db["PINES"].find({}))):
        if "text_date" in pines_info:
            continue

        note_data = db["NOTES"].find_one({'text_id' : pines_info['text_id']})
        text_date = note_data["text_date"]

        db["PINES"].update_one({"_id" : ObjectId(str(pines_info["_id"]))},
                                       { "$set": { "text_date" : text_date }})



if __name__ == "__main__":
    '''
    Performs updates to ensure compatibility on
    all relevant databases.
    '''
    ensure_patient_compatibility()
    ensure_annotation_compatibility()
    ensure_info_compatibility(pines_url=PINES_URL)
    ensure_pines_compatibility()
