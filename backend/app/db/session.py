"""Database engine/session management. SQLite (dev) / PostgreSQL (prod)."""
import re
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings


def _sqlite_url_path(url: str) -> Path | None:
    m = re.match(r"^sqlite(\+[a-z]+)?:///(.*)$", url)
    if m:
        return Path(m.group(2))
    return None


def build_engine(url: str | None = None, *, ensure_dir: bool = True):
    settings = get_settings()
    url = url or settings.database_url
    if url.startswith("sqlite"):
        p = _sqlite_url_path(url)
        if p is not None and ensure_dir:
            p.parent.mkdir(parents=True, exist_ok=True)
        return create_engine(
            url,
            connect_args={"check_same_thread": False} if "sqlite" in url else {},
            pool_pre_ping=True,
        )
    # PostgreSQL
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        _engine = build_engine()
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)

        if "sqlite" in str(_engine.url):
            @event.listens_for(_engine, "connect")
            def _fk_on(dbapi_conn, _):  # pragma: no cover
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.close()

    return _engine


def get_session_factory() -> sessionmaker:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def reset_engine_for_tests():
    """Allow tests to swap the DATABASE_URL before engine creation."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
