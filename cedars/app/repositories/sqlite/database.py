"""SQLite database connection and session management."""

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import config

# Get database path from config, default to local file
_db_path = config.get("SQLITE_DB_PATH", "cedars.db")
_database_url = f"sqlite:///{_db_path}"

# Create engine with connection pooling disabled for SQLite (thread safety)
engine = create_engine(
    _database_url,
    connect_args={"check_same_thread": False},
    echo=config.get("SQLITE_ECHO", "").lower() == "true",
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session() -> Session:
    """Get a new database session."""
    return SessionLocal()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db():
    """Initialize the database, creating all tables."""
    from .tables import Base
    Base.metadata.create_all(bind=engine)


def drop_db():
    """Drop all tables."""
    from .tables import Base
    Base.metadata.drop_all(bind=engine)
