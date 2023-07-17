"""
This file contatins the flask backend code to run the CEDARS web interface.
"""
from tempfile import mkdtemp
from flask import Flask, render_template, session
from flask import request, redirect
from flask_session import Session
from dotenv import load_dotenv
from mongodb_client import DatabaseConnector


load_dotenv()


DB_NAME = "PYCEDARS"


db_conn = DatabaseConnector(DB_NAME, "en_core_sci_lg")

app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

@app.after_request
def after_request(response):
    """
    Ensure responses aren't cached
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)


def update_session_variables(patient_id = None):
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

    session["patient_id"] = patient_id
    session["annotation_ids"] = db_conn.get_patient_annotation_ids(session["patient_id"])
    session["annotation_number"] = 0
    session["all_annotations_done"] = False

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

def get_initials(user_name):
    """
    Gets the initials from a name.

    Args:
        user_name (str) : Name of the researcher using the software.

    Returns:
        Initials (str) : A sting of the user's initials.

    Raises:
        None
    """

    words = user_name.split(" ")
    return "".join([word[0] for word in words])


@app.route("/no_remaining_annotations", methods=["GET", "POST"])
def no_remaining_annotations():
    """
    This is a flask function for the backend logic
                    for the no_remaining_annotations page.
    Runs if all annotations of a patient have been completed.

    Args:
        None

    Returns:
        None

    Raises:
        None
    """
    update_session_variables()
    return redirect("/")

@app.route("/search_patient", methods=["POST"])
def search_patient():
    """
    This is a flask function for the backend logic
                    for the search_patient page.
    There is no dedicated page for this logic, we simply update the
                        session variables and go back to the main page.
    Runs if all annotations of a patient have been completed.

    Args:
        None

    Returns:
        None

    Raises:
        None
    """
    update_session_variables(int(request.form["patient_id"]))
    return redirect("/")

# Pylint disabled as function has multipule IF statements as well as for using too many variables.
@app.route("/", methods=["GET", "POST"])
def index(): #pylint: disable=R0911, disable=R0912, disable= R0914
    """
    This is a flask function for the backend logic
                    for the search_patient page.
    Handels the backend logic for the main CEDARS page.

    Args:
        None

    Returns:
        None

    Raises:
        None
    """

    # Pylint disabled due to if-else with returns in both
    if request.method == "GET": #pylint: disable=R1705
        session["user"] = "Kayan Irani"

        if "patient_id" not in session.keys():
            update_session_variables() # takes first patient's data as default

        while len(session["annotation_ids"]) == 0: # all notes of that patient are annotated
            db_conn.mark_patient_reviewed(session['patient_id'])
            update_session_variables()

            if session["all_annotations_done"] is True: # all patients have been reviewed
                return render_template("annotations_complete.html")


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

        ldap_name = session["user"]
        session["annotation_id"] = annotation["_id"]


        user_initials = get_initials(ldap_name)
        comments = annotation["comments"]


        annotation_number = session["annotation_number"] + 1
        num_total_annotations = len(session["annotation_ids"])

        return render_template("index.html", name = ldap_name,
                            event_date = event_date, note_date = note_date,
                            pre_token_sentence = pre_token_sentence, token_word = token_word,
                            post_token_sentence = post_token_sentence,
                            pos_start = annotation_number,
                            total_pos = num_total_annotations, patient_id = patient_id,
                            comments = comments, full_note = full_note,
                            user_initials = user_initials)
    else:
        if request.form['submit_button'] == "new_date":
            new_date = request.form['date_entry']
            current_annotation_id = session["annotation_ids"][session["annotation_number"]]
            db_conn.update_annotation_date(current_annotation_id, new_date)

            return redirect("/")

        if request.form['submit_button'] == "del_date":
            current_annotation_id = session["annotation_ids"][session["annotation_number"]]
            db_conn.delete_annotation_date(current_annotation_id)
            return redirect("/")

        if request.form['submit_button'] == "comment":
            current_annotation_id = session["annotation_ids"][session["annotation_number"]]
            db_conn.add_annotation_comment(current_annotation_id, request.form['comment'])

            return redirect("/")

        if request.form['submit_button'] == "prev":
            if session["annotation_number"] > 0:
                session["annotation_number"] -= 1

            return redirect("/")

        if request.form['submit_button'] == "next":
            if session["annotation_number"] < (len(session["annotation_ids"]) - 1):
                session["annotation_number"] += 1

            return redirect("/")

        if request.form['submit_button'] == "adjudicate":
            current_annotation_id = session["annotation_ids"][session["annotation_number"]]
            db_conn.mark_annotation_reviewed(session["annotation_id"])

            session["annotation_ids"].pop(session["annotation_number"])

            if session["annotation_number"] >= len(session["annotation_ids"]):
                session["annotation_number"] -= 1

            return redirect("/")

        return redirect("/")

if __name__ == '__main__':
    app.run()