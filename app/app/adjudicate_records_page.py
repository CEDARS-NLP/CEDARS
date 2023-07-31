"""
This page contatins the functions and flask blueprints needed to run the /adjudicate_records page.
"""
from flask import Blueprint, render_template
from flask import session
from login_page import login_required, get_initials
from session_functions import update_session_variables
from mongodb_client import DatabaseConnector


adjudicate_records_page = Blueprint("adjudicate_records", __name__)

def split_on_key_word(sentence, word_start, word_end):
    """
    Used to split a sentence to isolate it's key word.

    Args:
        sentence (str) : String for the full sentence.
        word_start (int) : String index for the start of the key word.
        word_end (int) : String index for the end of the key word.

    Returns:
        Split sentence (tuple) : A tuple with three contents :
            1.  The sentence before the key word.
            2.  The key word.
            3.  The sentence after the key word.

    Raises:
        None
    """

    return (sentence[:word_start],
        sentence[word_start : word_end], sentence[word_end:])

@adjudicate_records_page.route("/adjudicate_records", methods=["GET"])
@login_required
def adjudicate_records():
    """
    This is a flask function for the backend logic 
                    for the  adjudicate_records page.
    Handels the backend logic for the main CEDARS page.

    Args:
        None

    Returns:
        None

    Raises:
        None
    """
    db_conn = DatabaseConnector()

    ldap_name = session["user"]
    proj_name = db_conn.get_proj_name()
    user_initials = get_initials(ldap_name)

    if "patient_id" not in session.keys():
        update_session_variables(db_conn) # returns first patient's data as default

    while len(session["annotation_ids"]) == 0: # all notes of that patient are annotated
        db_conn.mark_patient_reviewed(session['patient_id'])
        update_session_variables(db_conn)

        if session["all_annotations_done"] is True: # all patients have been reviewed
            return render_template("annotations_complete.html", user_initials = user_initials,
                                   proj_name = proj_name, is_admin = session.get('is_admin'))


    current_annotation_id = session["annotation_ids"][session["annotation_number"]]
    annotation = db_conn.get_annotation(current_annotation_id)
    note = db_conn.get_annotaion_note(current_annotation_id)
    patient_id = session['patient_id']

    sentence = annotation["sentence"]
    pre_token_sentence, token_word, post_token_sentence = split_on_key_word(sentence,
                                    annotation["start_index"], annotation["end_index"])
    full_note = note['text']

    note_date = str(note['text_date'].date()) # Format : YYYY-MM-DD
    if annotation['event_date']:
        event_date = str(annotation['event_date'].date()) # Format : YYYY-MM-DD
    else:
        event_date = "None"

    session["annotation_id"] = annotation["_id"]
    comments = annotation["comments"]


    annotation_number = session["annotation_number"] + 1
    num_total_annotations = len(session["annotation_ids"])


    # isLocked will be True if the patient_id that has been searched for is not in the database
    if session.get("hasBeenLocked") is None or session.get("hasBeenLocked") is False:
        is_locked = False
    else:
        is_locked = True
    session["hasBeenLocked"] = False

    return render_template("adjudicate_records.html", name = ldap_name,
                        event_date = event_date, note_date = note_date,
                        pre_token_sentence = pre_token_sentence, token_word = token_word,
                        post_token_sentence = post_token_sentence,
                        pos_start = annotation_number,
                        total_pos = num_total_annotations, patient_id = patient_id,
                        comments = comments, full_note = full_note,
                        user_initials = user_initials, proj_name = proj_name,
                        isLocked = is_locked, is_admin = session.get('is_admin'))
