"""One SQLAlchemy engine per database role, and a session() context manager."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from typing import Literal

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import settings

Role = Literal["admin", "ro", "rw"]


@cache
def engine(role: Role = "ro") -> Engine:
    url = {
        "admin": settings.database_url,
        "ro": settings.database_url_ro,
        "rw": settings.database_url_rw,
    }[role]
    return create_engine(url, pool_pre_ping=True)


@contextmanager
def session(role: Role = "ro") -> Iterator[Session]:
    """Commit on success, roll back on error. Tools use the default read-only role."""
    with Session(engine(role)) as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
