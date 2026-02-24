"""
PostgreSQL database connection and async session management.

This closely follows the standard async `connection.py` structure,
but is adapted to:
- use the existing central `app.core.settings` for configuration
- reuse URL normalisation and connection args from the sync engine
- keep all existing sync behaviour in `app.db.session` unchanged
"""

from typing import AsyncGenerator

import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.settings import settings, get_database_url
from app.db.base import Base  # reuse existing Base definition
from app.db.session import _normalize_database_url, _build_connect_args


logger = logging.getLogger(__name__)

# Async engine instance (lazy-initialised)
engine = None


def get_engine_kwargs() -> dict:
    """Get async engine configuration kwargs based on environment."""
    # Base kwargs mirror the sync engine behaviour
    engine_kwargs: dict = {
        "echo": settings.db_echo,
        "pool_recycle": settings.db_pool_recycle,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_pre_ping": True,
    }

    # For async engines, don't explicitly set QueuePool -- create_async_engine
    # automatically uses AsyncAdaptedQueuePool.  Only set NullPool when requested.
    if settings.app_env.lower() == "production":
        engine_kwargs["pool_size"] = settings.db_pool_size
    else:
        if settings.db_use_nullpool_in_dev:
            engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs["pool_size"] = settings.db_pool_size

    return engine_kwargs


def get_async_engine():
    """Get or create the async engine instance."""
    global engine
    if engine is None:
        database_url = get_database_url()
        normalized_url = _normalize_database_url(database_url)
        connect_args = _build_connect_args(normalized_url)

        engine = create_async_engine(
            normalized_url,
            connect_args=connect_args,
            **get_engine_kwargs(),
        )
    return engine


def get_session_maker():
    """Get async session maker."""
    return async_sessionmaker(
        get_async_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency to get async database session.

    Usage in FastAPI:
        @app.get("/users")
        async def get_users(db: AsyncSession = Depends(get_db)):
            ...
    """
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("Async database session error: %s", e)
            raise
        finally:
            await session.close()


async def init_db():
    """
    Initialize database tables for async engine.

    Note: In production, use Alembic migrations instead.
    """
    async with get_async_engine().begin() as conn:
        # Import models so they are registered on the metadata if needed.
        try:
            import app.db.models  # noqa: F401
        except ImportError:
            # Models package may not be present or may be loaded elsewhere.
            pass

        # Tables are managed by Alembic in this project; keep this a no-op.
        # await conn.run_sync(Base.metadata.create_all)
        pass

    logger.info("Async database initialisation completed")


async def close_db():
    """
    Close async database connections.
    """
    global engine
    if engine is not None:
        await engine.dispose()
    logger.info("Async database connections closed")


async def check_db_connection() -> bool:
    """
    Check async database connection health.

    Returns:
        True if connection is healthy, False otherwise
    """
    try:
        async with get_async_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error("Async database health check failed: %s", e)
        return False

