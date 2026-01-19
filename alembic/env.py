from logging.config import fileConfig
from alembic import context
import os
import sys
from pydantic_settings import BaseSettings


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.db.base import Base
from app.helpers.ingestion_pipeline.property.pgvector_store import PropertyEmbedding  # noqa: F401
from app.db.models.conversation import Conversation, ChatMessage  # noqa: F401


class Settings(BaseSettings):
    """Settings for Alembic migrations.
    
    Database URL should be set via DATABASE_URL environment variable or .env file.
    Never hardcode credentials in source code.
    """
    database_url: str = ""
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url():
    """Get database URL from environment variable if available, otherwise use default or alembic.ini.
    Uses the same connection logic as app/db/session.py for consistency.
    """
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        url = env_url
    else:
        ini_url = config.get_main_option("sqlalchemy.url")
        if ini_url:
            url = ini_url
        else:
            url = Settings().database_url
    
    if not url:
        raise ValueError(
            "DATABASE_URL is not set. Please set it in your .env file or environment variables."
        )
    
    # Use the same URL processing as app/db/session.py
    db_url = url
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    
    # Add prepare_threshold=0 (same as session.py)
    if "?" in db_url:
        if "prepare_threshold" not in db_url:
            db_url += "&prepare_threshold=0"
    else:
        db_url += "?prepare_threshold=0"
    
    # Add sslmode=require if not present (for cloud databases like Render.com)
    if "sslmode" not in db_url.lower():
        db_url += "&sslmode=require"
    
    return db_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_url()
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
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    Uses the app's engine directly to ensure consistency.

    """
    # Import the app's engine directly - it already has all the correct SSL/connection settings
    from app.db.session import engine as app_engine
    
    # Use the app's engine directly - it's already configured correctly
    # This ensures we use the exact same connection settings that work in the app
    with app_engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

