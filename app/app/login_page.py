from functools import wraps
from flask import Blueprint, render_template
from flask import redirect, session, request
from flask_login import UserMixin, LoginManager
from flask_login import login_user, logout_user
from mongodb_client import DatabaseConnector
from sentry_sdk import set_user


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    
    return decorated_function

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

login_page = Blueprint("login", __name__)

login_manager = LoginManager()

class User(UserMixin):
    def __init__(self, username):
        self.username = username
    
    def get_id(self):
        return self.username
    


@login_manager.user_loader
def load_user(username):
    return User(username)

@login_manager.unauthorized_handler
def unauthorized():
    return redirect("/login")

@login_page.route("/login", methods=["GET", "POST"])
def login():
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

    proj_name = db_conn.get_proj_name()
    if request.method == "POST":
        session.clear()

        admin_name = request.form.get("admin_username")
        if admin_name is not None and request.form.get("password") is not None:
            # Runs if an admin user has been created.
            db_conn.add_project_user(str(admin_name), str(request.form.get("password")))
            return redirect("/")

        # Ensure username was submitted
        username = request.form.get("username")
        if username is None:
            return redirect("/login")
        
        if username not in db_conn.get_users():
            return render_template("login.html", proj_name = proj_name,
                                show_invalid_login = True)
        

        # Ensure password was submitted
        password = request.form.get("password")
        if password is None:
            return redirect("/login")
        
        if db_conn.check_password(username, password) == False:
            return render_template("login.html", proj_name = proj_name,
                                show_invalid_login = True)
        

        load_user(User(username))
        set_user({'username' : username})
        session["user"] = username
    
        return redirect("/")
    else:
        if len(db_conn.get_users()) == 0:
            # Runs if no users exist in the database.
            # After admin is added
            return render_template("create_admin.html", proj_name = proj_name)
        
        return render_template("login.html", proj_name = proj_name)
    


@login_page.route('/logout', methods=["GET", "POST"])
def logout():
    logout_user()
    set_user(None)
    session.clear()
    return redirect("/login")