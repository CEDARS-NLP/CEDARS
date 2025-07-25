from enum import Enum
import time
from functools import wraps
from loguru import logger


def log_function_call(func):
    """Decorator to log function calls."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.debug(f"Python function {func.__name__} called with args")#: {args}, kwargs: {kwargs}")
        start_time = time.perf_counter()  # More precise than time.time()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        execution_time = (end_time - start_time)
        logger.debug(f"Python function {func.__name__} finished execution in {execution_time:.6f}s")
        return result
    return wrapper

class ReviewStatus(Enum):
    '''
    Enum to map to the review status of an annotation.
    There are three possible review states that an annotation can have :

    1. UNREVIEWED :- This annotation has not been reviewed
    2. REVIEWED :- This annotation has been reviewed
    3. SKIPPED :- This annotation has not been reviewed by an annotator,
                    but the note was taken after the date on which the event
                    was recorded and so the annotation is skipped.
    '''
    UNREVIEWED = 0
    REVIEWED = 1
    SKIPPED = 2

class PatientStatus(Enum):
    '''
    Enum to keep track of the review status for a patient.

    The possible patient statuses are :
    1. NO_ANNOTATIONS :- If no annotations were found in the notes for this patient.
    2. REVIEWED_WITH_EVENT :- The event for this patient was found and the annotations
                                before this event date have been reviewed.
    3. REVIEWED_NO_EVENT :- All annotations for this patient have been reviewed but
                                no event was found.
    4. UNDER_REVIEW :- This patient still has some unreviewed annotations left.
    '''
    NO_ANNOTATIONS = 0
    REVIEWED_WITH_EVENT = 1
    REVIEWED_NO_EVENT = 2
    UNDER_REVIEW = 3
