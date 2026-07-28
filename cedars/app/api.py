import os
from loguru import logger
from tenacity import retry, wait_exponential
import requests
from . import db
from .cedars_enums import log_function_call

@log_function_call
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
            health_check = requests.get(f'{pines_api_url}/healthcheck', verify=False)
            health_check = health_check.json()
            logger.info(f"Pines healthcheck: {health_check['status']}")
            if health_check['status'] == 'Healthy':
                return pines_api_url,False
            if health_check['status'] != 'Healthy': #logging as error instead of throwing an exception while EC2 spin up 
                logger.error(f'Issue found while performing healthcheck on the PINES server {pines_api_url}, got status : {health_check["status"]}.')
                return None,False

        except requests.exceptions.SSLError as e:
            logger.error(f'SSL error when trying to connect to {pines_api_url}: {e}.')
            return None, False


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

@log_function_call
def init_pines_connection(superbio_api_token = None):
    '''
    Initializes the PINES url in the INFO col.
    If no server is available this is marked as None.

    Args :
        - superbio_api_token (str) : Access token for superbio server if one is being used.
    
    Returns :
        (bool) : True if a valid pines url has been found.
                            False if not valid pines url available.
    '''
    project_info = db.get_info()
    project_id = project_info["project_id"]

    try:
        pines_url, is_url_from_api = load_pines_url(project_id,
                                        superbio_api_token=superbio_api_token)
        logger.info(f"pines instance available: {pines_url}, is_url_from_api: {is_url_from_api}")
    except requests.exceptions.HTTPError as e:
        logger.error(f"Got HTTP error when trying to start PINES server : {e}")
        pines_url, is_url_from_api = None, False
    except Exception as e:
        logger.error(f"Got error when trying to access PINES server : {e}")
        pines_url, is_url_from_api = None, False

    db.create_pines_info(pines_url, is_url_from_api)
    if pines_url is not None:
        return True

    return False

@log_function_call
def check_is_pines_available(superbio_api_token=None):
    is_pines_available = False

    try:
        if superbio_api_token is not None:
            is_pines_available = init_pines_connection(superbio_api_token)
        
        else: #send spin up request for EC2 instance to establish pine connection
            logger.info("Trying to connect PINES EC2 instance")
            is_pines_available = init_pines_connection(None)
        return is_pines_available
    except Exception as e:
        logger.error(f"Got error while trying to check PINES server availability : {e}")
        raise e

@log_function_call
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
    if api_url is None:
        return result
    
    if superbio_api_token is None:
        logger.error("No superbio token avalible to access URL.")
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

@log_function_call
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
