from flask import Blueprint, render_template
from flask import redirect, session, request
from login_page import login_required, get_initials
from werkzeug.utils import secure_filename
from mongodb_client import DatabaseConnector


def allowed_image_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
    
    extension = filename.split(".")[-1]

    return extension in ALLOWED_EXTENSIONS

proj_details_page = Blueprint("proj_details", __name__)

@proj_details_page.route("/proj_details", methods=["GET", "POST"])
@login_required
def proj_details():
    """
    
    Args:
        None

    Returns:
        None

    Raises:
        None
    """
    db_conn = DatabaseConnector()
    
    if request.method == "POST":
        if "proj_logo" not in request.files:
            return redirect("/proj_details")

        if "proj_logo" in request.files:
            file = request.files["proj_logo"]
            if allowed_image_file(secure_filename(file.filename)):
                file_path = "static/proj_logo.png"
                file.save(file_path)

        proj_name = request.form.get("proj_name")

        db_conn.update_proj_name(proj_name)

        return redirect("/proj_details")
    else:
        proj_name = db_conn.get_proj_name()
        user_name = session["user"]
        user_initials = get_initials(user_name)

        cedars_version = db_conn.get_curr_version()

        return render_template("proj_details.html", proj_name = proj_name,
                            user_initials = user_initials, cedars_version = cedars_version)