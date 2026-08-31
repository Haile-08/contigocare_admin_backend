"""Alembic environment configuration.

Loads the database URL from the application's settings so migrations
stay in sync with the running app configuration.
"""

from logging.config import fileConfig
from urllib.parse import quote_plus

from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from alembic import context
from app.core.config import settings
# Importing the package registers every table on SQLModel.metadata. A model
# missing from `app/models/__init__.py` is invisible to autogenerate.
import app.models  # noqa: F401

# Alembic Config object
config = context.config

# Set up Python logging from the ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Build the database URL from app settings. Migrations run on psycopg3 in sync
# mode — the same driver the app uses async, since psycopg2 went with the sync
# engine. A bare `postgresql://` here would resolve to psycopg2 and fail to import.
DATABASE_URL = (
    "postgresql+psycopg://"
    f"{quote_plus(settings.POSTGRES_USER)}:{quote_plus(settings.POSTGRES_PASSWORD)}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Point Alembic at our SQLModel metadata for autogenerate support
target_metadata = SQLModel.metadata

# Nothing external writes to this database any more: the analysis agent is
# stateless and holds no checkpointer, and long-term memory was removed. The set
# is kept, empty, so a future external table has an obvious place to be declared.
EXCLUDE_TABLES: set[str] = set()


def include_object(object, name, type_, reflected, compare_to):
    """Filter out tables managed by external systems."""
    if type_ == "table" and name in EXCLUDE_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Emits SQL to stdout instead of executing against the database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates an engine and runs migrations against the live database.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
