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
        # Track this session for monitoring
        AsyncConnectionManager.track_session(session)
        
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("Async database session error: %s", e)
            raise
        finally:
            try:
                await session.close()
            except Exception:
                pass
            finally:
                # Untrack session after cleanup
                AsyncConnectionManager.untrack_session(session)


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
        try:
            await engine.dispose()
            logger.info("✓ Async database engine disposed")
        except Exception as e:
            logger.warning("⚠️  Error disposing async engine: %s", e)


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


# -----------------------------------------------------------------------------
# Async Connection Management Utilities
# -----------------------------------------------------------------------------

class AsyncConnectionManager:
    """
    Centralized database connection manager for async connections.
    
    This class provides utilities for managing database connections
    and ensures proper cleanup of resources.
    """
    
    _active_sessions: set = set()
    
    @classmethod
    def track_session(cls, session: AsyncSession) -> AsyncSession:
        """Track an active session for cleanup monitoring."""
        cls._active_sessions.add(id(session))
        return session
    
    @classmethod
    def untrack_session(cls, session: AsyncSession) -> None:
        """Untrack a session after cleanup."""
        cls._active_sessions.discard(id(session))
    
    @classmethod
    def get_active_session_count(cls) -> int:
        """Get the number of tracked active sessions."""
        return len(cls._active_sessions)
    
    @classmethod
    def force_cleanup_all(cls) -> None:
        """Force cleanup of any remaining sessions (emergency use)."""
        if cls._active_sessions:
            logger.warning("⚠️  Force cleaning up %d tracked async sessions", len(cls._active_sessions))
            cls._active_sessions.clear()


async def close_all_connections() -> None:
    """
    Close ALL async database connections.
    
    This is the main entry point for connection cleanup during shutdown.
    Call this in the application lifespan shutdown handler.
    """
    logger.info("🧹 Closing all async database connections...")
    
    # Force cleanup of any tracked sessions
    AsyncConnectionManager.force_cleanup_all()
    
    # Dispose the engine
    await close_db()
    
    logger.info("✓ All async database connections closed")


async def shutdown_all_databases() -> None:
    """
    Shutdown ALL database connections (both sync and async).
    
    This is the MAIN entry point for complete database shutdown.
    It closes both async and sync engines.
    
    Usage in main.py lifespan:
        await shutdown_all_databases()
    """
    # Import sync connection module here to avoid circular imports
    from app.db.session import close_all_connections as close_sync_connections
    
    logger.info("🧹 Shutting down all database connections...")
    
    # 1. Close async connections first
    await close_all_connections()
    
    # 2. Close sync connections
    close_sync_connections()
    
    logger.info("✓ All database connections closed")


# Export AsyncConnectionManager for use in other modules
__all__ = [
    'get_db', 'close_db', 'close_all_connections', 'shutdown_all_databases',
    'check_db_connection', 'init_db', 'get_async_engine', 'get_session_maker',
    'AsyncConnectionManager'
]

