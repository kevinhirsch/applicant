"""Alembic environment. Pulls the DB URL from settings, targets our metadata."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from applicant.adapters.storage.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the runtime DB URL from settings (zero-CLI / env-driven).
# URL precedence: an explicit -x db_url=... (or DATABASE_URL env) wins; otherwise
# pull from settings; otherwise fall back to the alembic.ini placeholder.
_x_args = context.get_x_argument(as_dictionary=True)
_explicit_url = _x_args.get("db_url") or os.environ.get("DATABASE_URL")
if _explicit_url:
    config.set_main_option("sqlalchemy.url", _explicit_url)
else:
    try:
        from applicant.app.config import get_settings

        config.set_main_option("sqlalchemy.url", get_settings().database_url)
    except Exception:
        # Fall back to alembic.ini's placeholder if settings can't load.
        pass

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
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
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
