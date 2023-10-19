"""
This page contatins the functions and the flask blueprint for the login functionality.
"""
from functools import wraps
from flask import (
    Blueprint,
    render_template,
    flash,
    redirect,
    request,
    session,
    url_for
)
from flask_login import (
    UserMixin,
    LoginManager,
    logout_user,
    login_user,
    current_user
)

from werkzeug.security import check_password_hash, generate_password_hash
from bson import ObjectId
from . import db
# from sentry_sdk import set_user
bp = Blueprint("auth", __name__, url_prefix="/auth")

login_manager = LoginManager()


def admin_required(func):
    """Admin required decorator"""
    @wraps(func)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash('You do not have admin access.')
            return render_template('index.html', **db.get_info())
        return func(*args, **kwargs)
    return decorated_function


@login_manager.user_loader
def load_user(user_id):
    """Load a user"""
    user_data = db.get_user(user_id)
    if user_data:
        return User(user_data)
    return None


@login_manager.unauthorized_handler
def unauthorized():
    """Redirect unauthorized users to login page"""
    return redirect(url_for("auth.login"))


class User(UserMixin):
    """
    A user object based on the flask_login specifications.
    """
    def __init__(self, data):
        self._id = ObjectId(data["_id"])
        self.username = data["user"]
        self.password = data["password"]
        self.is_admin = data["is_admin"]

    def get_id(self):
        return str(self.username)


@bp.route("/register", methods=["GET", "POST"])
def register():
    """Register a new user"""
    if request.method == 'POST':
        username = request.form.get("username")
        password = request.form.get("password")
        error = None
        if not username or not password  or len(username.strip())==0 or len(password.strip())==0:
            error = "Username and password are required."

        existing_user = db.get_user(username)

        if existing_user:
            error = 'Username already exists.'

        if error is None:
            hashed_password = generate_password_hash(password)
            # Making the first registered user an admin
            is_admin = not len(db.get_project_users())>0

            db.add_user(
                username=username,
                password=hashed_password,
                is_admin=is_admin)

            flash('Registration successful.')
            return redirect(url_for('auth.login'))
        flash(error)
    return render_template('auth/register.html', **db.get_info())


@bp.route("/login", methods=["GET", "POST"])
def login():
    """Login a user"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = db.get_user(username)

        if user and check_password_hash(user['password'], password):
            login_user(User(user))
            flash('Login successful.')
            return render_template('index.html', **db.get_info())

        flash('Invalid credentials.')
        return redirect(url_for('auth.login'))
    if len(db.get_project_users()) == 0:
        return redirect(url_for('auth.register'))
    return render_template('auth/login.html',  **db.get_info())


@bp.route('/logout', methods=["GET", "POST"])
def logout():
    """Logout a user"""
    if session.get("patient_id"):
        db.set_patient_lock_status(int(session.get("patient_id")), False)

    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))
