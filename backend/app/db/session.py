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
    ensure_schema(eng)
    return eng


def ensure_schema(eng):
    """Idempotent lightweight migrations for columns added after the DB was
    first created (dev convenience; alembic remains the production path).
    Preserves existing rows."""
    from sqlalchemy import inspect, text
    insp = inspect(eng)

    def cols(tbl):
        return {c["name"] for c in insp.get_columns(tbl)}

    with eng.begin() as conn:
        # Innovation 5 — model lifecycle status on model_versions
        if "model_versions" in insp.get_table_names() and "status" not in cols("model_versions"):
            conn.execute(text("ALTER TABLE model_versions ADD COLUMN status VARCHAR(16) DEFAULT 'production'"))
        # Innovation 5 — queue item type on maintenance_queue
        if "maintenance_queue" in insp.get_table_names():
            tcols = cols("maintenance_queue")
            if "item_type" not in tcols:
                conn.execute(text("ALTER TABLE maintenance_queue ADD COLUMN item_type VARCHAR(16) DEFAULT 'change'"))
            # scenario_id must accept NULL for model-deploy items (SQLite has no
            # DROP NOT NULL — rebuild the table preserving data)
            scen = [c for c in insp.get_columns("maintenance_queue") if c["name"] == "scenario_id"]
            if scen and scen[0]["nullable"] is False:
                conn.execute(text("""
                    CREATE TABLE maintenance_queue_new (
                        id INTEGER NOT NULL,
                        line_id INTEGER NOT NULL,
                        scenario_id INTEGER,
                        station_code VARCHAR(16) NOT NULL,
                        change VARCHAR(256) NOT NULL,
                        priority VARCHAR(8) NOT NULL,
                        risk_level VARCHAR(8) NOT NULL,
                        estimated_duration_min INTEGER NOT NULL,
                        target_window FLOAT NOT NULL,
                        status VARCHAR(16) NOT NULL,
                        created_at FLOAT NOT NULL,
                        item_type VARCHAR(16),
                        PRIMARY KEY (id)
                    )"""))
                conn.execute(text("""
                    INSERT INTO maintenance_queue_new
                        (id, line_id, scenario_id, station_code, change, priority,
                         risk_level, estimated_duration_min, target_window, status,
                         created_at, item_type)
                    SELECT id, line_id, scenario_id, station_code, change, priority,
                           risk_level, estimated_duration_min, target_window, status,
                           created_at, COALESCE(item_type, 'change')
                    FROM maintenance_queue"""))
                conn.execute(text("DROP TABLE maintenance_queue"))
                conn.execute(text("ALTER TABLE maintenance_queue_new RENAME TO maintenance_queue"))
    return eng
