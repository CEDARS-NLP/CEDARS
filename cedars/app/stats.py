"""
This page contatins the functions and the flask blueprint for the /stats route.
"""
from flask import Blueprint, render_template
from flask_login import login_required
from . import db

bp = Blueprint("stats_page", __name__, url_prefix="/stats")

@bp.route('/')
@login_required
def stats_route():
    """
    This is a flask function for the backend logic
    for the stats route.

    It is used by the admin to view statistics of the query in the current project.
    The idea of the stats page is to give the reseacher an idea of the cohort.
    """

    stats = db.get_curr_stats()


    number_of_patients = stats["number_of_patients"]
    number_of_annotated_patients = stats["number_of_annotated_patients"]
    number_of_reviewed = stats["number_of_reviewed"]
    lemma_dist = stats['lemma_dist']

    return render_template("stats.html",
                            number_of_patients = number_of_patients,
                            number_of_annotated_patients = number_of_annotated_patients,
                            number_of_reviewed = number_of_reviewed,
                            lemma_dist = lemma_dist, **db.get_info())
