"""
Database session management for SQLAlchemy.

Provides engine, session factory, and FastAPI dependency for database connections.
"""
import os
import time
from typing import Generator, Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, DisconnectionError
from sqlalchemy.orm import Session, sessionmaker
from pydantic_settings import BaseSettings
import psycopg


# Constants
CONNECT_TIMEOUT = 60  # seconds (increased for remote databases that may be sleeping)
POOL_RECYCLE = 300  # 5 minutes
POOL_SIZE = 5
MAX_OVERFLOW = 10
POOL_TIMEOUT = 120  # seconds (increased for slow connections)
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 2  # seconds (increased initial delay)


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""
    database_url: str = ""
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


def _get_database_url() -> str:
    """
    Get database URL from environment or .env file.
    
    Returns:
        Database connection URL
        
    Raises:
        ValueError: If DATABASE_URL is not set
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        settings = DatabaseSettings()
        database_url = settings.database_url
    
    if not database_url:
        raise ValueError(
            "DATABASE_URL is not set. Please set it in your .env file or environment variables.\n"
            "Example: DATABASE_URL=postgresql://user:pass@host:5432/dbname"
        )
    
    return database_url


def _normalize_database_url(url: str) -> str:
    """
    Normalize database URL for psycopg driver and add connection parameters.
    
    Args:
        url: Original database URL
        
    Returns:
        Normalized database URL with psycopg driver and prepare_threshold
    """
    # Replace postgresql:// with postgresql+psycopg://
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    
    # Parse URL to add prepare_threshold parameter
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    
    # Add prepare_threshold if not present
    if "prepare_threshold" not in query_params:
        query_params["prepare_threshold"] = ["0"]
    
    # Reconstruct URL
    new_query = urlencode(query_params, doseq=True)
    normalized = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))
    
    return normalized


def _build_connect_args(url: str) -> dict:
    """
    Build connection arguments for SQLAlchemy engine.
    
    Args:
        url: Database URL
        
    Returns:
        Dictionary of connection arguments
    """
    connect_args = {
        "connect_timeout": CONNECT_TIMEOUT,
        "prepare_threshold": 0,
    }
    
    # Add keepalive settings for psycopg
    if "psycopg" in url:
        connect_args.update({
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        })
    
    # For remote databases (like Render), ensure SSL is properly configured
    # This helps with SSL connection stability for cloud databases
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    if "sslmode" not in query_params:
        # Default to require SSL for remote databases (Render, AWS RDS, etc.)
        connect_args["sslmode"] = "require"
    
    return connect_args


# Initialize database URL
database_url = _get_database_url()
normalized_url = _normalize_database_url(database_url)
connect_args = _build_connect_args(normalized_url)

# Create SQLAlchemy engine
engine: Engine = create_engine(
    normalized_url,
    pool_pre_ping=True,  # Test connections before using
    pool_recycle=POOL_RECYCLE,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    connect_args=connect_args,
    pool_timeout=POOL_TIMEOUT,
    pool_reset_on_return='rollback',
    echo=False,
)

# Configure PostgreSQL session-level timeouts to prevent idle transactions
# These are applied to EVERY connection in the pool
@event.listens_for(engine, "connect")
def set_postgresql_timeout(dbapi_conn, connection_record):
    """
    Set PostgreSQL-level timeouts to prevent idle transactions.
    
    - statement_timeout: Kill queries that run longer than 60 seconds
    - idle_in_transaction_session_timeout: Kill idle transactions after 60 seconds
    
    This is the MOST EFFECTIVE way to prevent "idle in transaction" issues.
    """
    cursor = dbapi_conn.cursor()
    try:
        # Kill queries that run longer than 60 seconds (60000 ms)
        cursor.execute("SET statement_timeout = '60000'")
        
        # Kill idle transactions after 60 seconds (60000 ms)
        # This is the KEY setting to prevent "idle in transaction"
        cursor.execute("SET idle_in_transaction_session_timeout = '60000'")
        
        # Optional: Set lock timeout to prevent long waits on locks
        cursor.execute("SET lock_timeout = '30000'")  # 30 seconds
        
        cursor.close()
        dbapi_conn.commit()
    except Exception as e:
        print(f"⚠️  Failed to set PostgreSQL timeouts: {e}")
        try:
            cursor.close()
        except:
            pass

# Note: pool_pre_ping=True already tests connections before use
# Additional error handling is done in get_db() and repository methods

# Create session factory
SessionLocal: sessionmaker[Session] = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session.
    
    Automatically handles:
    - Connection retries with exponential backoff
    - Rollback on exceptions
    - Session cleanup
    
    Yields:
        SQLAlchemy database session
        
    Raises:
        OperationalError: If database connection fails after retries
        
    Usage:
        @app.get("/endpoint")
        async def endpoint(db: Session = Depends(get_db)):
            # Use db here
            pass
    """
    db: Optional[Session] = None
    retry_delay = INITIAL_RETRY_DELAY
    
    # Retry connection with exponential backoff
    for attempt in range(MAX_RETRIES):
        try:
            db = SessionLocal()
            # Test the connection
            db.execute(text("SELECT 1"))
            break
        except (OperationalError, DisconnectionError) as e:
            if attempt < MAX_RETRIES - 1:
                print(f"⚠️  Database connection attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
                print(f"   Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                print(f"❌ Database connection failed after {MAX_RETRIES} attempts")
                raise
    
    if db is None:
        raise RuntimeError("Failed to create database session")
    
    try:
        yield db
    except (OperationalError, DisconnectionError) as e:
        # Check if it's a connection closed error
        error_str = str(e).lower()
        if any(phrase in error_str for phrase in [
            'connection has been closed',
            'terminating connection',
            'ssl connection has been closed',
            'connection closed unexpectedly'
        ]):
            # Invalidate the connection pool to force new connections
            try:
                engine.pool.invalidate()
                print("⚠️  Connection pool invalidated due to closed connection")
            except:
                pass
        try:
            db.rollback()
        except:
            pass
        raise
    except Exception:
        try:
            db.rollback()
        except:
            pass
        raise
    finally:
        # ✅ CRITICAL: Ensure transaction is closed before returning connection to pool
        # This prevents "idle in transaction" state
        try:
            # Check if transaction is still active
            if db.in_transaction():
                print("⚠️  Warning: Transaction still active in finally block, rolling back")
                db.rollback()
        except:
            pass
        
        try:
            db.close()
        except:
            pass

