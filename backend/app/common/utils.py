"""Small shared utilities used across the backend."""

from datetime import UTC, datetime


def now_utc() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)
