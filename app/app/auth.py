from flask_login import UserMixin, logout_user, login_user, LoginManager
from flask import Blueprint, render_template, redirect, url_for, request, session

auth = Blueprint('auth', __name__)

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
    return redirect(url_for('auth.login'))


def authenticate(username, password):
    return True


@auth.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['password'] and authenticate(request.form['username'], request.form['password']):
            login_user(User(username=request.form['username']))

            session['user'] = {
                'first_name': 'test',
                'last_name': 'user',
                'initials': 'TU'
            }

            return redirect(url_for('home'))
        else:
            return render_template('login.html', failed=True)
    else:
        return render_template('login.html')


@auth.route("/logout")
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
