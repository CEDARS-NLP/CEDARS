'''
This module is used to store functions that interact with and 
            perform logic on the session variables for the flask server.
'''
from flask import session
from mongodb_client import DatabaseConnector

def update_session_variables(db_conn, patient_id = None):
    '''
    Updates the session variables to store the following:
        1. The current patient's ID (patient_id).
        2. The IDs of all the annotations linked to that patient (annotation_ids).
        3. The current annotation being displayed to the user (annotation_number).
        4. Whether all annotations linked to that patient have been reviewed (all_annotations_done).

    If patient_id is None then we select the first patient that has not been reviewed.

    Args:
        patient_id (int) : Unique ID for a patient.

    Returns:
        None

    Raises:
        None
    '''


    db_conn = DatabaseConnector()

    # If None, select random
    if patient_id is None:
        patient_id = db_conn.get_patient()
        # will occur after get_patient() only when all patients have been reviewed
        if patient_id is None:
            session["patient_id"] = None
            session["annotation_ids"] = []
            session["annotation_number"] = 0
            session["all_annotations_done"] = True
            return

    if session.get("patient_id"):
        db_conn.set_patient_lock_status(session.get("patient_id"), False)

    session["patient_id"] = patient_id
    session["annotation_ids"] = db_conn.get_patient_annotation_ids(session["patient_id"])
    session["annotation_number"] = 0
    session["all_annotations_done"] = False
    
    db_conn.set_patient_lock_status(patient_id, True)
