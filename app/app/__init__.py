from flask_caching import Cache
from flask_login import login_required
from flask import Flask, redirect, url_for, render_template

cache = Cache()

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'}


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def create_app(config_filename):
    app = Flask(__name__)
    app.config.from_object(config_filename)

    cache.init_app(app)

    from app.auth import auth, login_manager
    login_manager.init_app(app)
    app.register_blueprint(auth)

    @app.route("/")
    def root():
        return redirect(url_for('auth.login'))

    @app.route("/home", methods=['GET', 'POST'])
    @login_required
    def home():
        return render_template('home.html')

    @app.errorhandler(404)
    def page_not_found(e):
        return redirect(url_for('home'))

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template(
            '500.html',
            type=type(e.original_exception).__name__,
            args=e.original_exception.args
        )

    return app
