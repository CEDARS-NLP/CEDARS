import multiprocessing

workers = multiprocessing.cpu_count() * 2 + 1
timeout = 120
bind = ':8050'
accesslog = '-'
errorlog = '/var/log/error.log'
disable_redirect_access_to_syslog = True
