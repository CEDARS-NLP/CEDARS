import multiprocessing as mp

from prometheus_flask_exporter.multiprocess import GunicornPrometheusMetrics
import os

workers = 4
threads = 4
worker_class = 'gthread'
timeout = 300
bind = ':5001'
keepalive = 5
preload_app = False
disable_redirect_access_to_syslog = True
accesslog = "/dev/null"

def when_ready(server):
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = "tmp/prometheus"
    GunicornPrometheusMetrics.start_http_server_when_ready(2001)


def child_exit(server, worker):
    GunicornPrometheusMetrics.mark_process_dead_on_child_exit(worker.pid)
