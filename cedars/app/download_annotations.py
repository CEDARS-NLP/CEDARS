"""
This page contatins the flask blueprint for the /download_annotations route.
"""
from flask import Blueprint
from flask import send_file
import pandas as pd
from .auth import login_required
from .mongodb_client import MongoConnector

download_annotations_page = Blueprint("download_annotations", __name__)

@download_annotations_page.route('/download_annotations')
@login_required
def download_file ():
    """
    This is a flask function for the backend logic 
                    for the download_annotations route.
    It will create a csv file of the current annotations and send it to the user.

    Args:
        None

    Returns:
        None

    Raises:
        None
    """
    db_conn = MongoConnector()

    data = db_conn.get_all_annotations()
    df = pd.DataFrame(data)
    path = "./static/annotations.csv"
    df.to_csv(path)

    return send_file(path, as_attachment=True)
