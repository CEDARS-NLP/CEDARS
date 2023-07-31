"""
This page contatins the flask blueprint for the /save_adjudications route.
"""
from flask import Blueprint
from flask import redirect, session, request
from login_page import login_required
from mongodb_client import DatabaseConnector

save_adjudications_page = Blueprint("save_adjudications", __name__)

@save_adjudications_page.route("/save_adjudications", methods=["POST"])
@login_required
def save_adjudications():
    """
    This is a flask function for the backend logic 
                    for the save_adjudications route.
    It is used to edit and review annotations.
    
    Args:
        None

    Returns:
        None

    Raises:
        None
    """
    db_conn = DatabaseConnector()
    if request.form['submit_button'] == "new_date":
        new_date = request.form['date_entry']
        current_annotation_id = session["annotation_ids"][session["annotation_number"]]
        db_conn.update_annotation_date(current_annotation_id, new_date)

    elif request.form['submit_button'] == "del_date":
        current_annotation_id = session["annotation_ids"][session["annotation_number"]]
        db_conn.delete_annotation_date(current_annotation_id)

    elif request.form['submit_button'] == "comment":
        current_annotation_id = session["annotation_ids"][session["annotation_number"]]
        db_conn.add_annotation_comment(current_annotation_id, request.form['comment'])

    elif request.form['submit_button'] == "prev":
        if session["annotation_number"] > 0:
            session["annotation_number"] -= 1

    elif request.form['submit_button'] == "next":
        if session["annotation_number"] < (len(session["annotation_ids"]) - 1):
            session["annotation_number"] += 1

    elif request.form['submit_button'] == "adjudicate":
        current_annotation_id = session["annotation_ids"][session["annotation_number"]]
        db_conn.mark_annotation_reviewed(session["annotation_id"])

        session["annotation_ids"].pop(session["annotation_number"])

        if session["annotation_number"] >= len(session["annotation_ids"]):
            session["annotation_number"] -= 1

    return redirect("/adjudicate_records")
