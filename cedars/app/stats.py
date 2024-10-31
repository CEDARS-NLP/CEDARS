"""
This page contatins the functions and the flask blueprint for the /stats route.
"""
from flask import Blueprint, render_template
from flask_login import login_required
from . import db

bp = Blueprint("stats_page", __name__, url_prefix="/stats")

def _elements_to_int(dictionary):
    """
    Converts the values in a dictionary to be integers.

    Args :
        - dictionary (dict) : A python dict where the values are floats.
    
    Returns :
        - dictionary (dict) : The input dictionary with the datatype
                                updated to int.
    """

    for key in dictionary:
        dictionary[key] = int(dictionary[key])

    return dictionary

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
    user_review_stats = stats['user_review_stats']

    # Convert the bar chat values to integers
    lemma_dist = _elements_to_int(lemma_dist)
    user_review_stats = _elements_to_int(user_review_stats)

    return render_template("stats.html",
                           number_of_patients=number_of_patients,
                           number_of_annotated_patients=number_of_annotated_patients,
                           number_of_reviewed=number_of_reviewed,
                           lemma_dist=lemma_dist,
                           user_review_stats=user_review_stats,
                           **db.get_info())
