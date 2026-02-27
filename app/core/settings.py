from __future__ import annotations

"""
Application-wide settings.

This module centralises configuration so other parts of the codebase
can depend on a single source of truth (similar to the standard
`app.core.settings` used in the reference connection module).
"""

import os
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    """Core application settings."""

    # Environment
    app_env: str = "development"

    # Database
    database_url: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle: int = 300  # 5 minutes
    db_pool_timeout: int = 120  # seconds
    db_echo: bool = False
    db_use_nullpool_in_dev: bool = False

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60
    redis_url: str = ""  # e.g. redis://localhost:6379/0; leave empty for in-memory storage

    # Observability
    otel_service_name: str = "unreserved-ai"
    otel_exporter_otlp_endpoint: str = ""  # e.g. http://localhost:4317
    app_version: str = "1.0.0"

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"

    def get_database_url(self) -> str:
        """
        Get database URL from environment or .env file.

        Mirrors the previous behaviour in `app.db.session`:
        - First check the DATABASE_URL environment variable.
        - Fallback to the `database_url` field loaded from .env.
        """
        database_url = os.getenv("DATABASE_URL") or self.database_url

        if not database_url:
            raise ValueError(
                "DATABASE_URL is not set. Please set it in your .env file or environment variables.\n"
                "Example: DATABASE_URL=postgresql://user:pass@host:5432/dbname"
            )

        return database_url

    def get_redis_url(self) -> str:
        """
        Get Redis URL for rate limit storage.
        Returns in-memory storage URI if Redis is not configured.
        """
        url = os.getenv("REDIS_URL") or self.redis_url
        return url.strip() if url else "memory://"


# Singleton settings instance used across the app
settings = AppSettings()


def get_database_url() -> str:
    """
    Convenience wrapper to get the database URL.

    This mirrors the pattern used in the standard connection module.
    """
    return settings.get_database_url()

