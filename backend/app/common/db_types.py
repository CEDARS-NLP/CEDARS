"""Shared SQLAlchemy column helpers used across model modules."""

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum


def enum_column(enum_cls, **kwargs) -> Column:
    """Enum column that persists the member VALUE (lowercase), not the NAME.

    SQLAlchemy's default binds the enum member name (e.g. "RUNNING"), but the
    Postgres enum types were created with the lowercase values ("running").
    values_callable forces the correct binding so Postgres accepts it. SQLite
    (tests) is lax about this, which is why the mismatch only surfaced on PG.
    """
    return Column(
        SAEnum(enum_cls, values_callable=lambda e: [m.value for m in e]),
        **kwargs,
    )
