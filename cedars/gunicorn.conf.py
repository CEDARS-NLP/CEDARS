import multiprocessing as mp
from prometheus_flask_exporter.multiprocess import GunicornInternalPrometheusMetrics

workers = 4
threads = 4
worker_class = 'gthread'
timeout = 300
bind = ':5001'
keepalive = 5
preload_app = False
disable_redirect_access_to_syslog = True
accesslog = "/dev/null"

def child_exit(server, worker):
    GunicornInternalPrometheusMetrics.mark_process_dead_on_child_exit(worker.pid)