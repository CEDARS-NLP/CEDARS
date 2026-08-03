"""Redis-backed adjudication review-state store.

Replaces the Flask server-side session that held the per-user adjudication state
(current patient, annotation index, navigation, event date, reviewed ids,
comments). State is pickled — exactly like flask-session did — so it preserves
the native objects the :class:`AdjudicationHandler` expects (``ObjectId``,
``datetime``, ``ReviewStatus`` enums). Keyed by ``(project_id, username)`` so a
reviewer can work on different projects independently.
"""
import pickle

from .. import queues

# Mirrors the original PERMANENT_SESSION_LIFETIME (60 minutes).
STATE_TTL_SECONDS = 60 * 60


def _key(username: str, project_id: str) -> str:
    return f"review_state:{project_id}:{username}"


def get_state(username: str, project_id: str):
    """Return the reviewer's saved state, or ``None``."""
    raw = queues.redis_conn.get(_key(username, project_id))
    return pickle.loads(raw) if raw else None


def set_state(username: str, project_id: str, state: dict):
    """Persist the reviewer's state (with a sliding TTL)."""
    queues.redis_conn.set(_key(username, project_id), pickle.dumps(state),
                          ex=STATE_TTL_SECONDS)


def clear_state(username: str, project_id: str):
    """Delete the reviewer's saved state."""
    queues.redis_conn.delete(_key(username, project_id))
