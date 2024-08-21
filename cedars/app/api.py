import os
from functools import wraps
from loguru import logger
import httpx
from tenacity import retry, wait_exponential
import requests
from . import db


class APIError(Exception):
    """An API Error Exception"""

    def __init__(self, error_msg):
        self.error_msg = error_msg

    def __str__(self):
        return "Got error when contacting API: ".format(self.error_msg)

def api_error_handler(func):
    """Decorator to handle API errors consistently."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e}")
            raise APIError(f"API request failed: {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"Request error occurred: {e}")
            raise APIError(f"Request failed: {str(e)}")
        except requests.exceptions.InvalidURL as e:
            logger.error(f'Invalid URL for API {e}.')
            raise APIError(f"API request failed due to invalid URL: {str(e)}")
        except requests.exceptions.ConnectionError as e:
            logger.error(f'Connection to API failed.')
            raise APIError(f"API request failed to connect: {str(e)}")

    return wrapper


@api_error_handler
def load_pines_url(project_id, superbio_api_token = None):
    '''
    if PINES_URL is not available in the ENV then
    - Start a PINES SERVER
    - With retry logic - keep making get requests
    - Get request gives a PINES URL
    - Call this URL for PINES predictions

    Args :
        - project_id (str) : The ID of the current CEDARS project.
        - superbio_api_token(str / None) : API token if using a superbio server,
                                    None if loading PINES via a different method.

    Returns :
        (pines_api_url, is_url_from_api)
        - pines_api_url (str / None) : The url of the PINES server if one is available.
        - is_url_from_api (bool) : True if this url belongs to a superbio server running PINES.
    
    Raises :
        - requests.exceptions.HTTPError
        - Custom error for PINES healthcheck
    '''

    env_url = os.getenv("PINES_API_URL")
    api_url = os.getenv("SUPERBIO_API_URL")
    if env_url is not None:
        # Get PINES api from .env
        pines_api_url = env_url
        is_url_from_api = False
        logger.info(f"Received url : {pines_api_url} for pines from ENV variables.")

        try:
            health_check = requests.get(f'{pines_api_url}/healthcheck')
            health_check = health_check.json()
            if health_check['status'] != 'Healthy':
                raise Exception(f'''Issue found while performing healthcheck on the 
                                PINES server {pines_api_url}, got status : {health_check["status"]}.''')
        except requests.exceptions.HTTPError as e:
            logger.error(f'Connection failed when trying to check status of PINES server {pines_api_url} : {e}.')
            return None, False
        except requests.exceptions.InvalidURL as e:
            logger.error(f'Invalid URL for PINES server {pines_api_url}.')
            return None, False
        except requests.exceptions.ConnectionError as e:
            logger.error(f'Could not connect to server {pines_api_url} to access PINES.')
            return None, False


    elif api_url is not None:
        # Get PINES api from API
        # Send a POST request to start the SERVER
        endpoint = f"cedars_projects/{project_id}/pines"

        if superbio_api_token is not None:
            headers = {"Authorization": f"Bearer {superbio_api_token}"}
        else:
            logger.error("No API token found, cannot authenticate with the server.")
            return None, False

        logger.info("Pinging", f'{api_url}/{endpoint}')
        logger.info("With header : ", headers, flush=True)
        response = requests.post(f'{api_url}/{endpoint}', headers=headers, data={})
        logger.info("POST responce", response, flush=True)

        if response.status_code != 200:
            raise requests.exceptions.HTTPError

        pines_api_url = load_pines_from_api(api_url, endpoint, headers)
        is_url_from_api = True
        logger.info(f"Received url : {pines_api_url} for pines from API.")
    else:
        logger.error("Unable to find any URL for PINES.")
        raise Exception("Unable to find any URL for PINES.")

    return pines_api_url, is_url_from_api

@retry(wait=wait_exponential(multiplier=1, min=4, max=600))
def load_pines_from_api(api_url, endpoint, headers):
    '''
    Gets the PINES url from an api using a get request.

    Expected return format from API :
    {
        'status': <status from cloudformation>,
        'url': <pines URL if it was spun up>
    }

    Args :
        - api_url (str) : URL for superbio server running PINES.
        - endpoint (str) : The endpoint on this server we are trying to reach.
        - headers (dict) : Any headers to provide with the request (such as passing a token).
    '''
    logger.info("Sending GET request to", f'{api_url}/{endpoint}', flush=True)
    data = requests.get(f'{api_url}/{endpoint}', headers=headers)
    json_data = data.json()
    logger.info("Got JSON", json_data, flush=True)
    return json_data['url']

@api_error_handler
def get_token_status(superbio_api_token):
    '''
    Function to test if a superbio token is still valid.

    Args :
        - superbio_api_token (str) : Temporary token used to connect to the
                                        superbio PINES servers.
    
    Returns :
        dict : {
                is_valid (bool) : True if this is a valid API token.
                has_expired (bool) : True if this is a valid token that has expired.
                token_info (str) : Details of token status, will contain an error message if
                                    the token is not valid.
        }

    '''
    result = {
        'is_valid' : False,
        'has_expired' : False,
        'token_info' : ''
    }

    api_url = os.getenv("SUPERBIO_API_URL")
    if api_url is None or superbio_api_token is None:
        logger.error("No server found to connect to.")
        result['token_info'] = 'Invalid API url or token.'
        return result

    endpoint = "cedars_projects"
    headers = {"Authorization": f"Bearer {superbio_api_token}"}
    try:
        response = requests.get(f'{api_url}/{endpoint}', headers=headers)
        data = response.json()
        if 'hits' in data:
            result['is_valid'] = True
            result['token_info'] = 'Token is working and has not expired.'
        elif 'msg' in data and data['msg'] == "Token has expired":
            logger.info("Superbio token has expired.")
            result['token_info'] = "Superbio token has expired."
            result['has_expired'] = True
    except requests.exceptions.HTTPError as e:
        logger.error(f"Encountered error {e} when trying to check token validity.")
        result['token_info'] = f"Encountered HTTP error {e}."
    except requests.exceptions.ConnectionError as e:
        logger.error(f'Could not connect to superbio server to check token validity.')
        result['token_info'] = f"Encountered Connection error {e}."

    return result

@api_error_handler
def kill_pines_api(project_id, superbio_api_token):
    '''
    Shutsdown remote PINES server if it is running.
    Currently only applicable when using the superbio API system.

    Args :
        - project_id (str) : The ID of the current CEDARS project.
        - superbio_api_token(str / None) : API token for the superbio server running PINES.
    '''

    if db.is_pines_api_running() and superbio_api_token is not None:
        # kill PINES server if using superbio API
        logger.info("Killing PINES server.")
        api_url = os.getenv("SUPERBIO_API_URL")
        if api_url is not None:
            endpoint = f"api/cedars_projects/{project_id}/pines"
            headers = {"Authorization": f"Bearer {superbio_api_token}"}

            try:
                requests.delete(f'{api_url}/{endpoint}', headers=headers)
            # TODO : Handle more types of exceptions
            # Might retry in case of certain exceptions
            except Exception as e:
                logger.error(f"Failed to shutdown remote PINES server due to error {e}.")

            # Set pines server status to False and delete the old url.
            db.update_pines_api_status(False)
