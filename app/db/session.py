from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://unreserved_user:KKnCtF4AGmJUU1xVjbunbefm3nchtK7k@dpg-d4mn42e3jp1c73a2gilg-a.oregon-postgres.render.com/unreserved"
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Ignore extra fields from .env (like GROQ_API_KEY, etc.)


# Get database URL from environment variable or use default
database_url = os.getenv("DATABASE_URL", Settings().database_url)
settings = Settings(database_url=database_url)

# Create engine
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,  # Set to True for SQL query logging
)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# Dependency for FastAPI routes
def get_db():
    """
    Dependency function that yields a database session.
    Used with FastAPI's Depends() for automatic session management.
    
    Usage:
        @app.get("/endpoint")
        def endpoint(db: Session = Depends(get_db)):
            # Use db here
            pass
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

