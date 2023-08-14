"""
This page contatins the functions and the flask blueprint for the /proj_details route.
"""
import pandas as pd
import logging
from pathlib import Path
from flask import (
    Blueprint, render_template,
    redirect, session, request, url_for, flash
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from .auth import admin_required, get_initials
from app import db
from . import NLP_processor



bp = Blueprint("ops", __name__, url_prefix="/ops")


def allowed_data_file(filename):
    """
    This function is used to check if a file has a valid extension for us to load tabular data from.
    
    Args:
        filepath (str) : The path to the file.
    Returns:
        (bool) : True if the file is of a supported type.
    """
    ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'json', 'parquet', 'pickle', 'pkl', 'xml'}

    extension = filename.split(".")[-1]

    return extension in ALLOWED_EXTENSIONS


def allowed_image_file(filename):
    """
    This function checks if a file is of a valid image filetype.

    Args:
        filename (str) : Name of the file trying to be loaded.
    Returns:
        (bool) : True if this is a supported image file type.
    """
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

    extension = filename.split(".")[-1]

    return extension in ALLOWED_EXTENSIONS


@bp.route("/project_details", methods=["GET", "POST"])
@admin_required
def project_details():
    """
    This is a flask function for the backend logic 
                    for the proj_details route.
    It is used by the admin to view and alter details of the current project.
    
    Args:
        None

    Returns:
        None

    Raises:
        None
    """

    if request.method == "POST":
        project_name = request.form.get("project_name")
        db.update_project_name(project_name)
        flash(f"Project name updated to {project_name}.")
           
        if "project_logo" in request.files:
            file = request.files["project_logo"]
            if allowed_image_file(secure_filename(file.filename)):
                file.save(Path("app/static") / "project_logo.png")
                flash("Logo updated successfully.")

        return render_template("index.html", **db.get_info())

    return render_template("ops/project_details.html", **db.get_info())


def load_pandas_dataframe(filepath):
    """
    This function is used to load tabular data from a file into a pandas DataFrame.
    
    Args:
        filepath (str) : The path to the file to load data from. 
            For valid file extensions refer to the allowed_data_file function above.
    Returns:
        (pandas DataFrame) : This is a dataframe with the data from the file.
    """
    extension = str(filepath).split(".")[-1]

    if extension == 'csv':
        return pd.read_csv(filepath)
    elif extension == 'xlsx':
        return pd.read_excel(filepath)
    elif extension == 'json':
        return pd.read_json(filepath)
    elif extension == 'parquet':
        return pd.read_parquet(filepath)
    elif extension == 'pickle' or extension == 'pkl':
        return pd.read_pickle(filepath)
    elif extension == 'xml':
        return pd.read_xml(filepath)
    
    return None

# Pylint disabled due to naming convention.
def EMR_to_mongodb(filepath): #pylint: disable=C0103
    """
    This function is used to open a csv file and load it's contents into the mongodb database.
    
    Args:
        filepath (str) : The path to the file to load data from.
        For valid file extensions refer to the allowed_data_file function above.
    Returns:
        None
    # """
    # if not allowed_data_file(filepath):
    #     return

    data_frame = load_pandas_dataframe(filepath)
    if data_frame is None:
        return

    id_list = data_frame["patient_id"].unique()
    logging.info("Starting document migration to mongodb database.")
    for i, p_id in enumerate(id_list):
        documents = data_frame[data_frame["patient_id"] == p_id]

        db.upload_notes(documents)

        logging.info("Documents uploaded for patient #%s", str(i + 1))

    logging.info("Completed document migration to mongodb database.")


@bp.route("/upload_data", methods=["GET", "POST"])
@admin_required
def upload_data():
    """
    This is a flask function for the backend logic to upload a file to the database.
    """

    # if not (session.get('is_admin') is True):
    #     return redirect("/")
    if request.method == "GET":
        return render_template("ops/upload_file.html", **db.get_info())
    
    if "data_file1" not in request.files and "data_file2" not in request.files:
        return redirect(url_for('ops.upload_data'))

    if "data_file1" in request.files:
        file = request.files["data_file1"]
        filename = current_user.username + "_" + secure_filename(file.filename)

        if not allowed_data_file(filename):
            return render_template("ops/upload_file.html", **db.get_info())
        
        file_path = Path("app/static") / filename
        file.save(file_path)
        EMR_to_mongodb(file_path)
        flash(f"{filename} uploaded successfully.")
        return redirect(url_for('ops.upload_query'))

    return render_template("ops/upload_file.html", **db.get_info())


@bp.route("/upload_query", methods=["GET", "POST"])
@admin_required
def upload_query():
    """
    This is a flask function for the backend logic 
    to upload a csv file to the database.
    """
    nlp_processor = NLP_processor.NLP_processor()

    if request.method == "GET":
        return render_template("ops/upload_query.html", **db.get_info())

    tag_query = {
        "exact": [False],
        "nlp_apply": [False],
        "include": [None],
        "exclude": [None]
    }

    search_query = request.form.get("regex_query")
    use_negation = False # bool(request.form.get("view_negations"))
    hide_duplicates = False # not bool(request.form.get("keep_duplicates"))
    skip_after_event = False # bool(request.form.get("skip_after_event"))


    db.save_query(search_query, use_negation,
                    hide_duplicates, skip_after_event, tag_query)

    db.empty_annotations()

    # TODO: use flask executor to run this in the background
    nlp_processor.automatic_nlp_processor()

    return redirect("/ops/adjudicate_records")


def _get_current_annotation_id():
        return session["annotation_ids"][session["annotation_number"]]

@bp.route("/save_adjudications", methods=["GET", "POST"])
@login_required
def save_adjudications():
    """
    Handle logic for the save_adjudications route.
    Used to edit and review annotations.
    """
    current_annotation_id = _get_current_annotation_id()

    def _update_annotation_date():
        new_date = request.form['date_entry']
        print(new_date)
        db.update_annotation_date(current_annotation_id, new_date)

    def _delete_annotation_date():
        db.delete_annotation_date(current_annotation_id)

    def _add_annotation_comment():
        db.add_annotation_comment(current_annotation_id, request.form['comment'])

    def _move_to_previous_annotation():
        if session["annotation_number"] > 0:
            session["annotation_number"] -= 1

    def _move_to_next_annotation():
        if session["annotation_number"] < (len(session["annotation_ids"]) - 1):
            session["annotation_number"] += 1

    def _adjudicate_annotation():
        db.mark_annotation_reviewed(current_annotation_id)
        session["annotation_ids"].pop(session["annotation_number"])
        if session["annotation_number"] >= len(session["annotation_ids"]):
            session["annotation_number"] -= 1

    actions = {
        'new_date': _update_annotation_date,
        'del_date': _delete_annotation_date,
        'comment': _add_annotation_comment,
        'prev': _move_to_previous_annotation,
        'next': _move_to_next_annotation,
        'adjudicate': _adjudicate_annotation
    }
  
    action = request.form['submit_button']
    if action in actions:
        actions[action]()

    return redirect("/ops/adjudicate_records")

    


# @bp.route("/save_adjudications", methods=["GET", "POST"])
# @login_required
# def save_adjudications():
#     """
#     This is a flask function for the backend logic 
#     for the save_adjudications route.
#     It is used to edit and review annotations.
#     """
#     if request.form['submit_button'] == "new_date":
#         new_date = request.form['date_entry']
#         current_annotation_id = session["annotation_ids"][session["annotation_number"]]
#         db.update_annotation_date(current_annotation_id, new_date)

#     elif request.form['submit_button'] == "del_date":
#         current_annotation_id = session["annotation_ids"][session["annotation_number"]]
#         db.delete_annotation_date(current_annotation_id)

#     elif request.form['submit_button'] == "comment":
#         current_annotation_id = session["annotation_ids"][session["annotation_number"]]
#         db.add_annotation_comment(current_annotation_id, request.form['comment'])

#     elif request.form['submit_button'] == "prev":
#         if session["annotation_number"] > 0:
#             session["annotation_number"] -= 1

#     elif request.form['submit_button'] == "next":
#         if session["annotation_number"] < (len(session["annotation_ids"]) - 1):
#             session["annotation_number"] += 1

#     elif request.form['submit_button'] == "adjudicate":
#         current_annotation_id = session["annotation_ids"][session["annotation_number"]]
#         db.mark_annotation_reviewed(session["annotation_id"])

#         session["annotation_ids"].pop(session["annotation_number"])

#         if session["annotation_number"] >= len(session["annotation_ids"]):
#             session["annotation_number"] -= 1

#     return redirect("/ops/adjudicate_records")

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
    """

    return (sentence[:word_start], sentence[word_start : word_end], sentence[word_end:])

@bp.route("/adjudicate_records", methods=["GET"])
@login_required
def adjudicate_records():
    """
    Serve the 'adjudicate_records' page. 
    Handle the logic associated with the main CEDARS page.
    """
    _initialize_session()
    
    if not session['annotation_ids']: 
        _prepare_for_next_patient()
        
        if not session["patient_id"]:
            session["all_annotations_done"] = True
            return render_template("ops/annotations_complete.html", **db.get_info())

    print(session["annotation_ids"])
    print(session["annotation_number"])
    current_annotation_id = session["annotation_ids"][session["annotation_number"]]
    annotation, note = _get_annotation_and_note_details(current_annotation_id)

    context = {
        'name': current_user.username,
        'event_date': _format_date(annotation.get('event_date')),
        'note_date': _format_date(note['text_date']),
        'pre_token_sentence': annotation['pre_token_sentence'],
        'token_word': annotation['token_word'],
        'post_token_sentence': annotation['post_token_sentence'],
        'pos_start': session["annotation_number"] + 1,
        'total_pos': len(session["annotation_ids"]),
        'patient_id': session['patient_id'],
        'comments': annotation["comments"],
        'full_note': note['text'],
        'isLocked': session.get("hasBeenLocked", False),
        **db.get_info()
    }

    session["hasBeenLocked"] = False

    return render_template("ops/adjudicate_records.html", **context)

def _initialize_session():
    if "patient_id" not in session:
        pt_id = db.get_patient()
        session.update({
            "patient_id": pt_id,
            "annotation_number": 0,
            "annotation_ids": db.get_patient_annotation_ids(pt_id)
        })

def _prepare_for_next_patient():
    db.mark_patient_reviewed(session['patient_id'])
    session.clear()
    _initialize_session()

def _get_annotation_and_note_details(annotation_id):
    annotation = db.get_annotation(annotation_id)
    note = db.get_annotation_note(annotation_id)
    sentence = annotation["sentence"]
    
    pre_token_sentence, token_word, post_token_sentence = split_on_key_word(
        sentence, annotation["start_index"], annotation["end_index"]
    )
    
    annotation.update({
        'pre_token_sentence': pre_token_sentence,
        'token_word': token_word,
        'post_token_sentence': post_token_sentence
    })

    return annotation, note

def _format_date(date_obj):
    if date_obj:
        return str(date_obj.date())
    return "None"


# @bp.route("/adjudicate_records", methods=["GET"])
# @login_required
# def adjudicate_records():
#     patient_id = db.get_patient()

#     if not patient_id:
#         flash("All patients are reviewed")
#         return redirect(url_for("ops.upload_data"))

#     session['patient_id'] = patient_id
#     index = request.args.get("index", 0, type=int)
#     session["annotation_number"] = index
#     session["annotation_ids"] = db.get_patient_annotation_ids(patient_id)
#     current_annotation_id = db.get_patient_annotation_ids(session['patient_id'])[session["annotation_number"]]
#     annotation = db.get_annotation(current_annotation_id)
#     note = db.get_annotation_note(current_annotation_id)

#     sentence = annotation["sentence"]
#     (pre_token_sentence,
#      token_word,
#      post_token_sentence) = split_on_key_word(sentence,
#                                               annotation["start_index"],
#                                               annotation["end_index"])
    
#     full_note = note["text"]
#     note_date = str(note['text_date'].date())
#     if annotation['event_date']:
#         event_date = str(annotation['event_date'].date()) # Format : YYYY-MM-DD
#     else:
#         event_date = "None"

#     # session["annotation_id"] = annotation["_id"]
#     comments = annotation["comments"]
#     annotation_number = session["annotation_number"] + 1
#     num_total_annotations = len(session["annotation_ids"])


#     # isLocked will be True if the patient_id that has been searched for is not in the database
#     if session.get("hasBeenLocked") is None or session.get("hasBeenLocked") is False:
#         is_locked = False
#     else:
#         is_locked = True
#     session["hasBeenLocked"] = False

#     return render_template("ops/adjudicate_records.html", name = current_user.username,
#                         event_date = event_date, note_date = note_date,
#                         pre_token_sentence = pre_token_sentence, token_word = token_word,
#                         post_token_sentence = post_token_sentence,
#                         pos_start = annotation_number,
#                         total_pos = num_total_annotations, patient_id = patient_id,
#                         comments = comments, full_note = full_note,
#                         isLocked = is_locked, **db.get_info())


# @bp.route("/adjudicate_records", methods=["GET"])
# @login_required
# def adjudicate_records():
#     """
#     This is a flask function for the backend logic 
#     for the  adjudicate_records page. Handels the backend logic
#     for the main CEDARS page.
#     """

#     if "patient_id" not in session.keys():
#         session["patient_id"] = db.get_patient()
#         session["annotation_number"] = 0
#         session["annotation_ids"] = db.get_patient_annotation_ids(session['patient_id'])

#     while len(session['annotation_ids']) == 0: # all notes of that patient are annotated
#         db.mark_patient_reviewed(session['patient_id'])
#         # get next unreviewed patient
#         session.clear()
#         session["patient_id"] = db.get_patient()
#         session["annotation_number"] = 0
#         session["annotation_ids"] = db.get_patient_annotation_ids(session['patient_id'])

#         if session["patient_id"] is None:
#             session["annotation_ids"] = []
#             session['patient_id'] = None
#             session["annotation_number"] = 0
#             session["all_annotations_done"] = True
#             return render_template("ops/annotations_complete.html", **db.get_info())
        
#     # current_annotation_id = session["annotation_ids"][session["annotation_number"]]
#     current_annotation_id = session["annotation_ids"][session["annotation_number"]]
#     annotation = db.get_annotation(current_annotation_id)
#     print(current_annotation_id)
#     note = db.get_annotation_note(current_annotation_id)
#     patient_id = session['patient_id']

#     sentence = annotation["sentence"]
#     (pre_token_sentence,
#      token_word,
#      post_token_sentence) = split_on_key_word(sentence,
#                                               annotation["start_index"],
#                                               annotation["end_index"])
#     full_note = note['text']

#     note_date = str(note['text_date'].date()) # Format : YYYY-MM-DD
#     if annotation['event_date']:
#         event_date = str(annotation['event_date'].date()) # Format : YYYY-MM-DD
#     else:
#         event_date = "None"

#     session["annotation_id"] = str(annotation["_id"])
#     comments = annotation["comments"]


#     annotation_number = session["annotation_number"] + 1
#     num_total_annotations = len(session["annotation_ids"])


#     # isLocked will be True if the patient_id that has been searched for is not in the database
#     if session.get("hasBeenLocked") is None or session.get("hasBeenLocked") is False:
#         is_locked = False
#     else:
#         is_locked = True
#     session["hasBeenLocked"] = False

#     return render_template("ops/adjudicate_records.html", name = current_user.username,
#                         event_date = event_date, note_date = note_date,
#                         pre_token_sentence = pre_token_sentence, token_word = token_word,
#                         post_token_sentence = post_token_sentence,
#                         pos_start = annotation_number,
#                         total_pos = num_total_annotations, patient_id = patient_id,
#                         comments = comments, full_note = full_note,
#                         isLocked = is_locked, **db.get_info())
