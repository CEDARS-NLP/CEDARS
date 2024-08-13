"""
This page contatins the functions and the flask blueprint for the login functionality.
"""
import os
from functools import wraps
import requests
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

import re
from dotenv import load_dotenv
from loguru import logger
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
    def __init__(self, data, api_token = None):
        self._id = ObjectId(data["_id"])
        self.username = data["user"]
        self.password = data["password"]
        self.is_admin = data["is_admin"]
        self.superbio_api_token = api_token

    def get_id(self):
        return str(self.username)

def check_password_policy(password):
    '''
    Checks a password to ensure that it meets our password strength policy.
    These checks include :
        1. Min length 8
        2. Atleast 2 uppercase letters
        3. Atleast 2 lowercase letters
        4. Atleast 2 numeric digits
        5. Atleast 2 special characters
    
    Args :
        - password (str) = password to be checked
    Returns :
        str = String containing the issue with the password.
                None if no issues are found.
    '''
    length_req = 8
    req_uppercase_chars = 2
    req_lowercase_chars = 2
    req_digits = 2
    req_special_chars = 2

    uppercase_chars = r"[A-Z]"
    lowercase_chars = r"[a-z]"
    digits = r"[0-9]"
    special_chars = r"[ !#$%&'()*+,-./[\\\]^_`{|}~"+r'"]'

    if len(password) < length_req:
        return f'Your password needs to be atleast {length_req} characters long.'
    elif ' ' in password:
        return f'No spaces are allowed in your password.'
    elif len(re.findall(uppercase_chars, password)) < req_uppercase_chars:
        return f'Your password needs atleast {req_uppercase_chars} uppercase characters.'
    elif len(re.findall(lowercase_chars, password)) < req_lowercase_chars:
        return f'Your password needs atleast {req_lowercase_chars} lowercase characters.'
    elif len(re.findall(digits, password)) < req_digits:
        return f'Your password needs atleast {req_digits} numeric digits.'
    elif len(re.findall(special_chars, password)) < req_special_chars:
        return f'Your password needs atleast {req_special_chars} special characters / symbols.'

    return None

@bp.route("/register", methods=["GET", "POST"])
def register():
    """Register a new user"""

    if request.method == 'POST':
        username = request.form.get("username")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        is_admin = request.form.get("isadmin") == "on"
        logger.info(f"Registering user {username} as admin: {is_admin}")

        # None if the password is in accordance with the policy.
        # A string with the error message if not.
        password_test_results = check_password_policy(password)

        error = None
        existing_user = db.get_user(username)
        if password != confirm_password:
            error = 'Passwords do not match.'
        elif not username or not password or len(username.strip()) == 0 or len(password.strip()) == 0:
            error = "Username and password are required."
        elif existing_user or username.lower() in ['cedars', 'pines']:
            error = 'Username already exists or reserved. Please choose a different one.'
        elif password_test_results is not None:
            error = password_test_results

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
    logger.info(f"Verifying token with {api_url}")
    logger.info(f"Headers: {headers}")
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

    logger.info(f"Token: {token}")
    logger.info(f"User ID: {user_id}")
    logger.info(f"Project ID: {os.getenv('CEDARS_PROJECT_ID')}")
    user_data = verify_external_token(token,
                                      user_id=user_id,
                                      project_id=os.getenv("CEDARS_PROJECT_ID"))
    logger.info(f"User data: {user_data}")
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
        user = User(db.get_user(username), api_token = token)
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
