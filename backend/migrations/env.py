"""Alembic env — pulls URL from app settings (env-driven)."""
import re
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.db import models  # noqa: F401 — register metadata
from app.db.session import build_engine  # noqa: F401 — keeps engine logic in one place

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)


def _ensure_sqlite_dir(url: str) -> None:
    """Fresh checkouts have no data/ directory yet — SQLite cannot create its
    database file inside a missing folder, so create the parent first.
    (Mirrors app.db.session.build_engine behavior; root-cause fix for
    `alembic upgrade head` failing on a clean clone / in CI.)"""
    m = re.match(r"^sqlite(\+[a-z]+)?:///(.*)$", url)
    if m and m.group(2):  # skip sqlite:///:memory:
        Path(m.group(2)).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.database_url)

target_metadata = models.Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch="sqlite" in settings.database_url,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch="sqlite" in settings.database_url,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
