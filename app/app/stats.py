from flask import Blueprint, render_template
from flask import session
from login_page import login_required, get_initials
from mongodb_client import DatabaseConnector

stats_page = Blueprint("stats_page", __name__)

@stats_page.route('/stats')
@login_required
def stats():
    db_conn = DatabaseConnector()

    proj_name = db_conn.get_proj_name()
    user_name = session["user"]
    user_initials = get_initials(user_name)

    stats = db_conn.get_curr_stats()


    number_of_patients = stats["number_of_patients"]
    number_of_annotated_patients = stats["number_of_annotated_patients"]
    number_of_reviewed = stats["number_of_reviewed"]


    return render_template("stats.html", proj_name = proj_name,
                            user_initials = user_initials,
                            number_of_patients = number_of_patients,
                            number_of_annotated_patients = number_of_annotated_patients,
                            number_of_reviewed = number_of_reviewed)