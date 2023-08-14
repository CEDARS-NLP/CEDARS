"""
This page contatins the functions and the flask blueprint for the login functionality.
"""
from functools import wraps
from flask import (
    Blueprint,
    render_template,
    g,
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
from app import db
# from sentry_sdk import set_user
bp = Blueprint("auth", __name__, url_prefix="/auth")

login_manager = LoginManager()


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash('You do not have admin access.')
            return render_template('index.html', **db.get_info())
        return f(*args, **kwargs)
    return decorated_function


def get_initials(username):
    words = username.split(" ")
    return "".join([word[0] for word in words])


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


@login_manager.user_loader
def load_user(user_id):
    user_data = db.get_user(user_id)
    if user_data:
        return User(user_data)
    return None

@login_manager.unauthorized_handler
def unauthorized():
    return redirect(url_for("auth.login"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == 'POST':
        username = request.form.get("username")
        password = request.form.get("password")
        print(username)
        print(password)
        if not username or not password:
            flash("Username and password are required.")
            return redirect(url_for('auth.register'))
        

        existing_user = db.get_user(username)
        
        if existing_user:
            flash('Username already exists.')
            return redirect(url_for('auth.register'))

        hashed_password = generate_password_hash(password)
        is_admin = False if len(db.get_project_users())>0 else True  # Making the first registered user an admin
        
        print("reach here")
        db.add_user(
            username=username,
            password=hashed_password,
            is_admin=is_admin)

        flash('Registration successful.')
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html', **db.get_info())


@bp.route("/login", methods=["GET", "POST"])
def login():
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
    return render_template('auth/login.html',  **db.get_info())


@bp.route('/logout', methods=["GET", "POST"])
def logout():
    if session.get("patient_id"):
        db.set_patient_lock_status(int(session.get("patient_id")), False)

    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))
