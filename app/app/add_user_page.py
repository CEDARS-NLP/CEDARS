from flask import Blueprint, render_template
from flask import redirect, session, request
from login_page import login_required, get_initials
from mongodb_client import DatabaseConnector

add_user_page = Blueprint("add_user", __name__)

@add_user_page.route("/add_user", methods=["GET", "POST"])
@login_required
def add_user():
    """
    Login page.
    
    Args:
        None

    Returns:
        None

    Raises:
        None
    """

    db_conn = DatabaseConnector()

    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username") or not request.form.get("password"):
            return redirect("/add_user")
        
        db_conn.add_project_user(str(request.form.get("username")), str(request.form.get("password")))
        
    
        return redirect("/add_user")
    else:
        proj_name = db_conn.get_proj_name()
        user_name = session["user"]
        user_initials = get_initials(user_name)

        curr_users = db_conn.get_project_users()

        return render_template("add_user.html", proj_name = proj_name,
                            user_initials = user_initials, curr_users = curr_users)