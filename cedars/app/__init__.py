"""
Entrypoint for the flask application.
"""

__version__ = "0.1.0"
__author__ = "Rohan Singh"

import os
from flask import Flask, render_template, session
from flask_session import Session
from loguru import logger
import rq
from redis import Redis

sess = Session()


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


def create_app(config_filename=None):
    """Create flask application"""
    cedars_app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), "static"))
    if config_filename:
        logger.info(f"Loading config from {config_filename}")
        cedars_app.config.from_object(config_filename)

    cedars_app.config["UPLOAD_FOLDER"] = os.path.join(cedars_app.instance_path)
    cedars_app.config["SESSION_TYPE"] = "redis"
    cedars_app.config["SESSION_REDIS"] = Redis.from_url(cedars_app.config["RQ"]['redis_url'])

    cedars_app.config['SESSION_PERMANENT'] = False
    cedars_app.config['SESSION_USE_SIGNER'] = True  # Sign the session ID cookie for security
    cedars_app.config['SESSION_COOKIE_SAMESITE'] = 'None'  # Allow cross-site cookies
    cedars_app.config['SESSION_COOKIE_SECURE'] = True  # Required for SameSite=None
    cedars_app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access for security

    sess.init_app(cedars_app)
    rq_init_app(cedars_app)

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
