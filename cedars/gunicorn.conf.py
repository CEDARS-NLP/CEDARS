import multiprocessing as mp

workers = 4
worker_class = 'uvicorn.workers.UvicornWorker'
timeout = 300
bind = ':8000'
keepalive = 5
preload_app = False
disable_redirect_access_to_syslog = True
accesslog = "/dev/null"

