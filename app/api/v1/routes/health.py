"""
Comprehensive health check endpoint for the Property Chat API.
Checks database connectivity, LLM API, vector stores, embedding service, and internet connectivity.
"""
from typing import Dict, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from contextlib import contextmanager
import httpx

from app.db.session import engine, SessionLocal
from app.services.rag_pipeline.llms import get_llm_client, get_model_name
from app.helpers.ingestion_pipeline.shared.openai_embeddings import OpenAIEmbeddings

router = APIRouter(prefix="/api/v1/health", tags=["health"])

# Constants
GOOGLE_CHECK_TIMEOUT = 5.0
LLM_API_TIMEOUT = 10.0


# ------------------------------------------------------------------------------
# Response Models
# ------------------------------------------------------------------------------
class ServiceStatus(BaseModel):
    """Status of an individual service check."""
    status: str = Field(..., description="Status: 'ok' or 'error'")
    message: str = Field(..., description="Status message")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "ok",
                "message": "Service is reachable"
            }
        }


class HealthCheckResponse(BaseModel):
    """Comprehensive health check response."""
    status: str = Field(..., description="Overall status: 'ok' or 'error'")
    timestamp: str = Field(..., description="ISO timestamp of the check")
    services: Dict[str, Any] = Field(..., description="Individual service statuses")


# ------------------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------------------
@contextmanager
def get_db_session():
    """Context manager for database sessions in health checks."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _check_table_exists(db, table_name: str) -> bool:
    """Helper to check if a table exists in the database."""
    result = db.execute(text("""
        SELECT EXISTS(
            SELECT 1 FROM information_schema.tables 
            WHERE table_name = :table_name
        )
    """), {"table_name": table_name})
    return result.scalar() or False


def _get_table_count(db, table_name: str) -> int:
    """
    Helper to get row count for a table.
    Note: table_name is validated by _check_table_exists first, so it's safe.
    Using identifier quoting for safety.
    """
    result = db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
    return result.scalar() or 0


# ------------------------------------------------------------------------------
# Health Check Functions
# ------------------------------------------------------------------------------
def check_google() -> Dict[str, Any]:
    """
    Pings Google to check internet connectivity.
    Returns a dict with status and optional error message.
    """
    try:
        with httpx.Client(timeout=GOOGLE_CHECK_TIMEOUT) as client:
            response = client.get("https://www.google.com", follow_redirects=True)
            if response.status_code == 200:
                return {"status": "ok", "message": "Google is reachable"}
            else:
                return {"status": "error", "message": f"Google returned status {response.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def check_database() -> Dict[str, Any]:
    """
    Checks PostgreSQL database connectivity.
    Returns a dict with status and optional error message.
    """
    try:
        with engine.connect() as conn:
            # Test basic connection
            result = conn.execute(text("SELECT 1"))
            result.scalar()
            
            # Check if pgvector extension is installed
            pgvector_check = conn.execute(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"))
            pgvector_installed = pgvector_check.scalar()
            
            return {
                "status": "ok",
                "message": "Database is reachable",
                "pgvector_installed": pgvector_installed
            }
    except OperationalError as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}"}
    except Exception as e:
        return {"status": "error", "message": f"Database check failed: {str(e)}"}


def check_llm_api() -> Dict[str, Any]:
    """
    Checks OpenAI LLM API availability.
    Returns a dict with status and optional error message.
    """
    try:
        llm_client = get_llm_client()
        model_name = get_model_name()
        
        # Test with a minimal API call
        response = llm_client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5,
            timeout=LLM_API_TIMEOUT
        )
        
        return {
            "status": "ok",
            "message": "LLM API is reachable",
            "model": model_name,
            "response_received": bool(response)
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"LLM API check failed: {str(e)}"
        }


def check_vector_store() -> Dict[str, Any]:
    """
    Checks vector store accessibility (property_embeddings and generic_knowledge tables).
    Returns a dict with status and optional error message.
    """
    try:
        with get_db_session() as db:
            # Check property_embeddings table
            property_table_exists = _check_table_exists(db, "property_embeddings")
            property_count = _get_table_count(db, "property_embeddings") if property_table_exists else 0
            
            # Check generic_knowledge table
            generic_table_exists = _check_table_exists(db, "generic_knowledge")
            generic_count = _get_table_count(db, "generic_knowledge") if generic_table_exists else 0
            
            # Test a simple vector query if tables exist
            vector_query_works = False
            if property_table_exists and property_count > 0:
                try:
                    # Try a simple query to verify table is accessible
                    db.execute(text("""
                        SELECT COUNT(*) FROM property_embeddings 
                        WHERE listing_id IS NOT NULL 
                        LIMIT 1
                    """))
                    vector_query_works = True
                except Exception:
                    pass
            
            return {
                "status": "ok",
                "message": "Vector store is accessible",
                "property_embeddings": {
                    "table_exists": property_table_exists,
                    "chunk_count": property_count
                },
                "generic_knowledge": {
                    "table_exists": generic_table_exists,
                    "chunk_count": generic_count
                },
                "vector_query_works": vector_query_works
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Vector store check failed: {str(e)}"
        }


def check_embedding_service() -> Dict[str, Any]:
    """
    Checks OpenAI embedding service availability.
    Returns a dict with status and optional error message.
    """
    try:
        embedding_client = OpenAIEmbeddings()
        
        # Test embedding generation with a simple string
        test_text = "health check test"
        embeddings = embedding_client.encode([test_text], convert_to_numpy=False)
        
        if embeddings and len(embeddings) > 0:
            embedding_dim = len(embeddings[0]) if embeddings[0] else 0
            return {
                "status": "ok",
                "message": "Embedding service is working",
                "model": embedding_client.model,
                "embedding_dimension": embedding_dim
            }
        else:
            return {
                "status": "error",
                "message": "Embedding service returned empty result"
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Embedding service check failed: {str(e)}"
        }


@router.get("/", response_model=HealthCheckResponse)
async def health_check() -> Dict[str, Any]:
    """
    Comprehensive health check endpoint.
    Checks all critical services: internet connectivity, database, LLM API, vector stores, and embedding service.
    
    Returns:
        - 200 OK if all services are healthy
        - 503 Service Unavailable if any service is unhealthy
    """
    # Run all health checks
    google_status = check_google()
    database_status = check_database()
    llm_status = check_llm_api()
    vector_store_status = check_vector_store()
    embedding_status = check_embedding_service()
    
    # Determine overall status
    all_checks = [google_status, database_status, llm_status, vector_store_status, embedding_status]
    overall_status = "ok" if all(
        check["status"] == "ok" for check in all_checks
    ) else "error"
    
    # Build response
    response = {
        "status": overall_status,
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "internet_connectivity": google_status,
            "database": database_status,
            "llm_api": llm_status,
            "vector_store": vector_store_status,
            "embedding_service": embedding_status
        }
    }
    
    # Return 503 if any service is unhealthy
    if overall_status == "error":
        raise HTTPException(status_code=503, detail=response)
    
    return response

