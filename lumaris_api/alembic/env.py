"""Alembic environment.

Schema authority for change-management: `alembic upgrade head` builds/updates the schema from the
SAME SQLAlchemy models `create_all` uses (Base.metadata), so migrations and the models can never
drift. Importing `db` here would normally build the schema as an import side-effect (db runs
init_db() on import); we set PETABYTE_SKIP_INIT_DB=1 first so Alembic controls schema creation
during the migration run instead.
"""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

load_dotenv()
# Don't let importing `db` build the schema on import — Alembic owns it during a migration.
os.environ["PETABYTE_SKIP_INIT_DB"] = "1"

import db  # noqa: E402  — registers ALL models on Base.metadata (54 tables, no relationships)

target_metadata = db.Base.metadata

config = context.config
_db_url = os.getenv("DATABASE_URL")
if _db_url:
    config.set_main_option("sqlalchemy.url", _db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """'offline' mode — emit SQL against a URL, no DBAPI needed."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """'online' mode — run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
