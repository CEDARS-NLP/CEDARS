"""
Entrypoint for the flask application.
"""

__version__ = "0.1.0"
__author__ = "Rohan Singh"

import os
from flask import Flask, render_template
from flask_session import Session
from flask_mail import Mail
from loguru import logger
import rq
from redis import Redis
from dotenv import load_dotenv

load_dotenv()
sess = Session()
EMAIL_CONNECTOR = None

def rq_init_app(cedars_rq):
    """Initialize the rq app"""
    cedars_rq.redis = Redis.from_url(cedars_rq.config["RQ"]['redis_url'])
    cedars_rq.task_queue = rq.Queue(cedars_rq.config["RQ"]['task_queue_name'],
                                    connection=cedars_rq.redis,
                                    default_timeout=cedars_rq.config["RQ"]['job_timeout'])
    cedars_rq.ops_queue = rq.Queue(cedars_rq.config["RQ"]['ops_queue_name'],
                                   connection=cedars_rq.redis,
                                   default_timeout=cedars_rq.config["RQ"]['job_timeout'])

    cedars_rq.extensions['rq'] = cedars_rq
    return cedars_rq

def init_app_email_config(cedars_app, host_email, app_password):
    """
    Initializes the configuration to allow the CEDARS application to send emails
    in order to verify a user's email address and send them project updates over email.
    """
    if host_email is not None and app_password is not None:
        cedars_app.config['MAIL_SERVER'] = 'smtp.gmail.com'
        cedars_app.config['MAIL_PORT'] = 587
        cedars_app.config['MAIL_USERNAME'] = host_email
        cedars_app.config['MAIL_PASSWORD'] = app_password
        cedars_app.config['MAIL_USE_TLS'] = True
        cedars_app.config['MAIL_USE_SSL'] = False
        cedars_app.config['MAIL_DEFAULT_SENDER'] = host_email
        mail_connection = Mail(cedars_app)
        return mail_connection
    else:
        logger.error("No host email / app password found. Skipping email configuration.")
        return None

def create_app(config_filename=None):
    """Create flask application"""
    global EMAIL_CONNECTOR

    cedars_app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), "static"))
    if config_filename:
        logger.info(f"Loading config from {config_filename}")
        cedars_app.config.from_object(config_filename)

    cedars_app.config["UPLOAD_FOLDER"] = os.path.join(cedars_app.instance_path)
    cedars_app.config["SESSION_TYPE"] = "redis"
    cedars_app.config["SESSION_REDIS"] = Redis.from_url(cedars_app.config["RQ"]['redis_url'])

    sess.init_app(cedars_app)
    rq_init_app(cedars_app)

    EMAIL_CONNECTOR = init_app_email_config(cedars_app,
                                            os.getenv("HOST_EMAIL"),
                                            os.getenv("HOST_EMAIL_APP_PASSWORD"))

    from . import auth
    auth.login_manager.init_app(cedars_app)
    cedars_app.register_blueprint(auth.bp)

    from . import ops
    cedars_app.register_blueprint(ops.bp)

    from . import stats
    cedars_app.register_blueprint(stats.bp)

    @cedars_app.route('/', methods=["GET"])
    def homepage():
        return render_template('index.html')

    return cedars_app
