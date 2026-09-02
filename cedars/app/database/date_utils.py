"""Date normalization helpers for SQL date columns and API boundaries."""

from datetime import date, datetime
from typing import Union


def normalize_date(value: Union[str, date, datetime]) -> date:
    """Return a SQL-compatible date from supported ingestion values."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid date format: {value!r}. Expected YYYY-MM-DD.") from exc
    if hasattr(value, "to_pydatetime"):
        converted = value.to_pydatetime()
        if isinstance(converted, datetime):
            return converted.date()
        if isinstance(converted, date):
            return converted
    raise ValueError(f"Unsupported date value: {value!r} ({type(value).__name__}).")