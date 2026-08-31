'''
db_session.py

Session-factory helpers shared by every module in cedars/app/database/.

Every DB function in this package accepts a `Session` (not a raw `Engine`).
Callers are expected to obtain a session via `session_scope(engine)` (or by
building a long-lived factory with `make_session_factory(engine)` and calling
it themselves), so that transaction/commit/rollback handling is consistent
across the global application database and every per-project database.
'''

from contextlib import contextmanager

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from ..cedars_enums import log_function_call

logger.enable(__name__)


def make_session_factory(engine) -> sessionmaker:
    '''
    Builds a reusable `sessionmaker` bound to the given engine (global or project).
    Callers that issue many sessions against the same engine (e.g. a request-scoped
    dependency) should cache the factory rather than calling this on every request.
    '''
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
@log_function_call
def session_scope(engine):
    '''
    Context manager yielding a `Session` bound to `engine`.
    Commits on success, rolls back and re-raises on any exception, always closes.
    '''
    session = Session(bind=engine, expire_on_commit=False, future=True)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
