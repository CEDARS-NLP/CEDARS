"""Compatibility symbols for the reference adjudication algorithms."""

import time
from enum import Enum
from functools import wraps


class ReviewStatus(Enum):
    UNREVIEWED = 0
    REVIEWED = 1
    SKIPPED = 2


class PatientStatus(Enum):
    NO_ANNOTATIONS = 0
    REVIEWED_WITH_EVENT = 1
    REVIEWED_NO_EVENT = 2
    UNDER_REVIEW = 3


class AnnotationStatus:
    STATUS_UNREVIEWED = "U"
    STATUS_REVIEWED = "R"
    STATUS_SKIPPED = "S"


def log_function_call(function):
    """Preserve the reference decorator without logging sensitive arguments."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        started_at = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            _ = time.perf_counter() - started_at

    return wrapper
