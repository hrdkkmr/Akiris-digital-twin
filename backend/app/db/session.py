"""Engine/session factory. Same models run on SQLite (local) or PostgreSQL (docker)."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ..core.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or get_settings().database_url
    kwargs = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        engine = create_engine(url, **kwargs)
        from sqlalchemy import event
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # write-heavy ingest friendliness
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()
    else:
        engine = create_engine(url, **kwargs)
    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(url: str | None = None):
    """Create all tables (idempotent)."""
    eng = make_engine(url) if url else engine
    from .. import models  # noqa: F401  (register all entities)
    Base.metadata.create_all(eng)
    return eng
