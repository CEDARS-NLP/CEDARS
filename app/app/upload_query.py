from flask import Blueprint, render_template
from flask import redirect, session, request
from login_page import login_required, get_initials
from mongodb_client import DatabaseConnector
from session_functions import update_session_variables
from NLP_processor import NLP_processor

upload_query_page = Blueprint("upload_query", __name__)


@upload_query_page.route("/upload_query", methods=["GET", "POST"])
@login_required
def upload_query():
    """
    This is a flask function for the backend logic 
                    to upload a csv file to the database.

    Args:
        None

    Returns:
        None

    Raises:
        None
    """
    db_conn = DatabaseConnector()
    nlp_processor = NLP_processor()

    user_name = session["user"]
    user_initials = get_initials(user_name)
    proj_name = db_conn.get_proj_name()

    if request.method == "GET":
        return render_template("upload_query.html",
                               user_initials=user_initials,
                               proj_name=proj_name)
    else:
        tag_query = {"exact": [False],
                     "nlp_apply": [False],
                     "include": [None],
                     "exclude": [None]
                     }

        search_query = request.form.get("regex_query")
        use_negation = bool(request.form.get("view_negations"))
        hide_duplicates = not bool(request.form.get("keep_duplicates"))
        skip_after_event = bool(request.form.get("skip_after_event"))
        
        db_conn.save_query(search_query, use_negation,
                           hide_duplicates, skip_after_event, tag_query)
        
        db_conn.empty_annotations()

        nlp_processor.automatic_nlp_processor(db_conn, search_query)

        update_session_variables(db_conn)

        return redirect("/adjudicate_records")

