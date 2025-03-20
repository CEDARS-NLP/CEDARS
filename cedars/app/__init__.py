"""
Entrypoint for the flask application.
"""
import os
import sys
from flask import Flask, redirect, render_template
from flask_session import Session
import logging
from loguru import logger
from dotenv import dotenv_values
import rq
import rq_dashboard
from redis import Redis
from prometheus_flask_exporter.multiprocess import GunicornInternalPrometheusMetrics
from . import auth
from . import ops
from . import stats

environment = os.getenv('ENV', 'local')
config = dotenv_values(".env")
sess = Session()


def rq_init_app(cedars_rq):
    """Initialize the rq app"""
    cedars_rq.redis = Redis.from_url(cedars_rq.config["RQ"]['redis_url'])
    cedars_rq.task_queue = rq.Queue(cedars_rq.config["RQ"]['task_queue_name'],
                                    connection=cedars_rq.redis,
                                    default_timeout=cedars_rq.config["RQ"]['job_timeout'])
    cedars_rq.ops_queue = rq.Queue(cedars_rq.config["RQ"]['ops_queue_name'],
                                   connection=cedars_rq.redis,
                                   default_timeout=cedars_rq.config["RQ"]['operation_timeout'])

    cedars_rq.extensions['rq'] = cedars_rq

    # Rq-dashboard support
    cedars_rq.config.from_object(rq_dashboard.default_settings)
    cedars_rq.config["RQ_DASHBOARD_REDIS_URL"] = cedars_rq.config["RQ"]['redis_url']
    rq_dashboard.blueprint.before_request(auth.rq_admin_check)
    rq_dashboard.web.setup_rq_connection(cedars_rq)
    cedars_rq.register_blueprint(rq_dashboard.blueprint,
                                    url_prefix=config['RQ_DASHBOARD_URL'])

    return cedars_rq


def create_app(config_filename=None):
    """Create flask application"""
    cedars_app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), "static"))
    if config_filename:
        logger.info(f"Loading config from {config_filename}")
        cedars_app.config.from_object(config_filename)

    cedars_app.config["UPLOAD_FOLDER"] = os.path.join(cedars_app.instance_path)
    metrics = GunicornInternalPrometheusMetrics(cedars_app)
    metrics.info('app_info', 'CEDARS Application', version='1.0.0')

    sess.init_app(cedars_app)
    rq_init_app(cedars_app)

    auth.login_manager.init_app(cedars_app)
    cedars_app.register_blueprint(auth.bp)

    cedars_app.register_blueprint(ops.bp)

    cedars_app.register_blueprint(stats.bp)

    setup_logging()

    @cedars_app.route('/', methods=["GET"])
    def homepage():
        if auth.current_user.is_authenticated and auth.current_user.is_admin:
            return redirect("/stats")
        elif auth.current_user.is_authenticated:
            return redirect("/ops/adjudicate_records")
        else:
            return render_template('index.html', **ops.db.get_info())

    @cedars_app.route('/about', methods=["GET"])
    def about():
        if auth.current_user.is_authenticated:
            return render_template("about.html", **ops.db.get_info())
        else:
            return render_template('index.html', **ops.db.get_info())


    return cedars_app

def setup_logging():
    """Setup logging"""
    """Configure Loguru as the primary logger and disable unwanted logs"""

    # 🔴 Remove default Loguru handler (avoid duplicate logs)
    logger.remove()

    # ✅ Setup Loguru logging (only INFO and above)
    logger.add(sys.stdout,
               format="{time} {level} {message}",
               level="DEBUG",
               colorize=True)

    # 🔴 Suppress Flask's werkzeug logs (disable request logs)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    # ✅ Redirect Python's `logging` module logs to Loguru
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            level = logger.level(record.levelname).name if record.levelname in logger._core.levels else "DEBUG"
            logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=logging.DEBUG)

    # 🔴 Suppress RQ Worker Debug Logs
    logging.getLogger("rq.worker").setLevel(logging.DEBUG)
    logging.getLogger("rq.queue").setLevel(logging.DEBUG)