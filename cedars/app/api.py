import os
from typing import Optional

from loguru import logger
import requests
from .cedars_enums import log_function_call
from .database import get_current_project_engine
from .database.db_projects import update_pines_api_status, update_pines_api_url

PINES_HEALTH_TIMEOUT = (5, 15)


def _configured_pines_url() -> str:
    url = (os.getenv("PINES_API_URL") or "").strip().rstrip("/")
    if not url:
        raise RuntimeError("PINES_API_URL is not configured")
    if not url.startswith(("http://", "https://")):
        raise ValueError("PINES_API_URL must use http:// or https://")
    return url


@log_function_call
def get_pines_health() -> dict:
    '''Return validated health metadata from the configured PINES server.'''
    url = _configured_pines_url()
    response = requests.get(f"{url}/healthcheck", timeout=PINES_HEALTH_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    threshold = data.get("classification_threshold")
    if data.get("status") != "Healthy":
        raise RuntimeError(f"PINES health status is {data.get('status')!r}")
    if not isinstance(data.get("model"), str) or not data["model"].strip():
        raise ValueError("PINES health response is missing model")
    if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        raise ValueError("PINES health response has an invalid classification_threshold")
    return {
        "available": True,
        "url": url,
        "model": data["model"],
        "classification_threshold": float(threshold),
    }

@log_function_call
def load_pines_url(project_id: Optional[str] = None):
    '''Return the self-hosted PINES URL after a successful healthcheck.'''
    del project_id
    return get_pines_health()["url"], False

@log_function_call
def init_pines_connection() -> bool:
    '''Validate and persist the self-hosted PINES connection.'''
    try:
        health = get_pines_health()
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        logger.error(f"PINES is unavailable: {exc}")
        update_pines_api_status(get_current_project_engine(), False)
        return False

    update_pines_api_url(get_current_project_engine(), health["url"])
    update_pines_api_status(get_current_project_engine(), True)
    logger.info(f"PINES model {health['model']} is available at {health['url']}")
    return True

@log_function_call
def check_is_pines_available() -> bool:
    return init_pines_connection()
