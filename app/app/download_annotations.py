from flask import Blueprint
from login_page import login_required
from flask import send_file
import pandas as pd
from mongodb_client import DatabaseConnector

download_annotations_page = Blueprint("download_annotations", __name__)

@download_annotations_page.route('/download_annotations')
@login_required
def downloadFile ():
    db_conn = DatabaseConnector()

    data = db_conn.get_reviewed_annotations()
    df = pd.DataFrame(data)
    path = "static/annotations.csv"
    df.to_csv(path)

    return send_file(path, as_attachment=True)