import requests
from tenacity import retry, wait_fixed

@retry(wait=wait_fixed(2))
def get_pines_url(host, port):
    r = requests.post(f"http://{host}:{port}", data={'data': 'pines_url_request'})
    return r.text