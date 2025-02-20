import multiprocessing as mp
workers = 4
threads = 4
worker_class = 'gthread'
timeout = 300
bind = ':5001'
keepalive = 5
preload_app = False
disable_redirect_access_to_syslog = True
accesslog = "/dev/null"
