"""
This page contatins the functions and the flask blueprint for the login functionality.
"""
from functools import wraps
from flask import Blueprint, render_template
from flask import redirect, session, request
from flask_login import UserMixin, LoginManager
from flask_login import logout_user
from sentry_sdk import set_user
from mongodb_client import DatabaseConnector


def login_required(f):
    """
    This is a function decorator that ensures that the current user is logged in.
    """
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
    """
    A user object based on the flask_login specifications.
    """
    def __init__(self, username):
        '''
        Stores the username when a new user is created.

        Args:
            username (str) : Name of the new user

        Returns:
            None

        Raises:
            None
        '''
        self.username = username

    def get_id(self):
        '''
        Returns the username for this user

        Args:
            None

        Returns:
            username (str) : Name of the user

        Raises:
            None
        '''
        return self.username



@login_manager.user_loader
def load_user(username):
    '''
    Creates a User object based on the flask_login specifications.

    Args:
        username (str) : Name of the user we need to load

    Returns:
        user (User) : User object that inherits UserMixin from flask_login

    Raises:
        None
    '''
    return User(username)

@login_manager.unauthorized_handler
def unauthorized():
    '''
    Handeler for when an unautorized user tries to gain access.

    Args:
        None

    Returns:
        flask redirect to login page

    Raises:
        None
    '''
    return redirect("/login")

@login_page.route("/login", methods=["GET", "POST"])
def login():
    """
    This is a flask function for the backend logic 
                    for the login route.
    It is used to log users in and to create the admin the first time the application runs.
    
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
            db_conn.add_project_user(str(admin_name), str(request.form.get("password")), is_admin=True)

            load_user(User(admin_name))
            set_user({'username' : admin_name})
            session["user"] = admin_name
            session["is_admin"] = True
            return redirect("/")

        # Ensure username was submitted
        username = request.form.get("username")
        if username is None:
            return redirect("/login")

        if username not in db_conn.get_project_users():
            return render_template("login.html", proj_name = proj_name,
                                show_invalid_login = True, is_admin = session.get('is_admin'))

        # Ensure password was submitted
        password = request.form.get("password")
        if password is None:
            return redirect("/login")

        if db_conn.check_password(username, password) is False:
            return render_template("login.html", proj_name = proj_name,
                                show_invalid_login = True, is_admin = session.get('is_admin'))


        load_user(User(username))
        set_user({'username' : username})
        session["user"] = username

        if db_conn.is_admin_user(username):
            session['is_admin'] = True
        else:
            session['is_admin'] = False

        return redirect("/")
    else:
        if len(db_conn.get_project_users()) == 0:
            # Runs if no users exist in the database.
            # After admin is added
            return render_template("create_admin.html", proj_name = proj_name,
                                   is_admin = session.get('is_admin'))

        return render_template("login.html", proj_name = proj_name,
                               is_admin = session.get('is_admin'))



@login_page.route('/logout', methods=["GET", "POST"])
def logout():
    """
    This is a flask function for the backend logic 
                    for the logout route.
    It is used to logout users.
    
    Args:
        None

    Returns:
        None

    Raises:
        None
    """
    if session.get("patient_id"):
        db_conn = DatabaseConnector()
        db_conn.set_patient_lock_status(int(session.get("patient_id")), False)

    logout_user()
    set_user(None)
    session.clear()
    return redirect("/login")
