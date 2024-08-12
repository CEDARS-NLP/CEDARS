"""
This page contatins the functions and the flask blueprint for the login functionality.
"""
import os
import requests
from functools import wraps
from flask import (
    Blueprint,
    render_template,
    flash,
    redirect,
    request,
    session,
    url_for,
    jsonify
)
from flask_login import (
    UserMixin,
    LoginManager,
    logout_user,
    login_user,
    current_user
)

from password_strength import PasswordPolicy
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash
from bson import ObjectId
from . import db
# from sentry_sdk import set_user

load_dotenv()
bp = Blueprint("auth", __name__, url_prefix="/auth")

login_manager = LoginManager()
login_manager.needs_refresh_message = u"Session timed out, please re-login"

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

    # Password strength policy
    policy = PasswordPolicy.from_names(
                    length=8,  # min length: 8
                    uppercase=2,  # need min. 2 uppercase letters
                    numbers=2,  # need min. 2 digits
                    special=2,  # need min. 2 special characters
                    )

    if request.method == 'POST':
        username = request.form.get("username")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        is_admin = request.form.get("isadmin") == "on"
        print(f"Registering user {username} as admin: {is_admin}")

        # This result holds all of the tests that failed the password policy check
        password_test_results = policy.test(password)

        error = None
        existing_user = db.get_user(username)
        if password != confirm_password:
            error = 'Passwords do not match.'
        elif not username or not password or len(username.strip()) == 0 or len(password.strip()) == 0:
            error = "Username and password are required."
        elif existing_user or username.lower() in ['cedars', 'pines']:
            error = 'Username already exists or reserved. Please choose a different one.'
        elif len(password_test_results) != 0:
            # There are policy checks which failed
            # Ask to correct the first failed check
            failed_test = password_test_results[0]
            if 'Length' in str(failed_test):
                error = f'Your password needs to be atleast {failed_test.length} characters long.'
            elif 'Uppercase' in str(failed_test):
                error = f'Your password needs atleast {failed_test.count} uppercase characters.'
            elif 'Numbers' in str(failed_test):
                error = f'Your password needs atleast {failed_test.count} numeric digits.'
            elif 'Special' in str(failed_test):
                error = f'Your password needs atleast {failed_test.count} special characters / symbols.'

        if error is None:
            hashed_password = generate_password_hash(password)
            # Making the first registered user an admin
            no_admin = not len(db.get_project_users()) > 0

            if no_admin and not is_admin:
                is_admin = True
                flash('First user registered is an admin.')

            db.add_user(
                username=username,
                password=hashed_password,
                is_admin=is_admin)

            flash('Registration successful.')
            if no_admin:
                login_user(User(db.get_user(username)))

            return render_template('index.html', **db.get_info())
        flash(error)
    return render_template('auth/register.html', **db.get_info())


def verify_external_token(token, project_id, user_id):
    """Verify the bearer token with the external API"""
    # Replace this URL with your actual external API endpoint
    api_url = f'{os.getenv("SUPERBIO_API_URL")}/users/{user_id}/cedars_projects/{project_id}'
    headers = {"Authorization": f"Bearer {token}"}
    # TODO: print to log
    print(f"Verifying token with {api_url}")
    print(f"Headers: {headers}")
    try:
        response = requests.get(api_url, headers=headers, verify=True)
        if response.status_code == 200:
            # Assuming the API returns user data on successful verification
            return response.json()
        return None
    except requests.RequestException:
        return None


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


@bp.route("/token-login", methods=["POST"])
def token_login():
    """Login a user using the bearer token received from the frontend"""
    token = request.json.get('token')
    user_id = request.json.get('user_id')
    if not token:
        return jsonify({"error": "No token provided"}), 400

    # TODO: print to log
    print(f"Token: {token}")
    print(f"User ID: {user_id}")
    print(f"Project ID: {os.getenv('CEDARS_PROJECT_ID')}")
    user_data = verify_external_token(token,
                                      user_id=user_id,
                                      project_id=os.getenv("CEDARS_PROJECT_ID"))
    print(f"User data: {user_data}")
    if user_data:
        username = user_data["user"].get('email')
        existing_user = db.get_user(username)
        if not existing_user:
            # Create a new user with data from the external API
            db.add_user(
                username=username,
                password=generate_password_hash(token),  # Store hashed token as password
                is_admin=True if "admin" in user_data["user"].get('institution_roles') else False
            )
        user = User(db.get_user(username))
        login_user(user)
        return jsonify({"message": "Login successful via external API."}), 200
    return jsonify({"error": "Invalid token or API error."}), 401


@bp.route('/logout', methods=["GET", "POST"])
def logout():
    """Logout a user"""
    if session.get("patient_id"):
        db.set_patient_lock_status(int(session.get("patient_id")), False)

    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))
