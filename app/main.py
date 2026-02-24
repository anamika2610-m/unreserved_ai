"""
FastAPI application for Property Chat API.

Run with:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    
Or:
    python -m uvicorn app.main:app --reload
"""
# Import config first to set up environment variables before other imports
import app.config  # noqa: F401

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.api.v1.routes.chat import router as chat_router
from app.core.exceptions import AppException, app_exception_handler
from app.core.rate_limiter import limiter, rate_limit_exceeded_handler, rate_limit
from app.db.connection import close_db
from app.api.v1.routes.sync import router as sync_router
from app.api.v1.routes.voice import router as voice_router
# from app.api.v1.routes.voice_realtime import router as voice_realtime_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.admin import router as admin_router
from app.api.v1.routes.activity import router as activity_router
from app.scheduler import start_summary_scheduler

# Application metadata
API_VERSION = "1.0.0"
API_TITLE = "Unreserved Property Chat API"
API_DESCRIPTION = "RESTful API for conversational property listing queries"

# CORS configuration
# Note: allow_origins=["*"] is permissive - restrict in production
CORS_ORIGINS = [
    # "*",
    "https://staging.unreservedrealestate.com.au/"
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    summary_task = start_summary_scheduler()
    try:
        yield
    finally:
        if summary_task and not summary_task.done():
            summary_task.cancel()
            try:
                await summary_task
            except asyncio.CancelledError:
                pass
        await close_db()


# Create FastAPI app
app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Rate limiting (SlowAPI)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Centralized app exceptions (ValidationError, DatabaseError, ExternalServiceError, etc.)
app.add_exception_handler(AppException, app_exception_handler)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(chat_router)
app.include_router(sync_router)
app.include_router(voice_router)
app.include_router(admin_router)  # Admin endpoints (property summaries, etc.)
app.include_router(activity_router)  # Activity tracking endpoints (tone adaptation)

# Voice realtime router (WebSocket) - disabled by default
# To enable: Set ENABLE_VOICE_REALTIME=true in .env file
# ENABLE_VOICE_REALTIME = os.getenv("ENABLE_VOICE_REALTIME", "false").lower() == "true"
# if ENABLE_VOICE_REALTIME:
#     app.include_router(voice_realtime_router)

app.include_router(health_router)


@app.get("/health")
async def simple_health():
    """Simple health check endpoint for Docker/Kubernetes healthchecks."""
    return {"status": "healthy"}


@app.get("/rate-limit-test")
@rate_limit("3/minute")  # Strict limit so you can trigger 429 easily
async def rate_limit_test(request: Request):
    """
    Test endpoint to verify rate limiting.
    Limit: 3 requests per minute per IP. 4th request within a minute returns 429.
    """
    return {"ok": True, "message": "Rate limit not exceeded"}


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "service": API_TITLE,
        "version": API_VERSION,
        "status": "running",
        "endpoints": {
            "chat": "/api/v1/chat/message",
            "health": "/api/v1/health",
            "voice_transcribe": "/api/v1/voice/transcribe",
            "voice_transcribe_and_chat": "/api/v1/voice/transcribe-and-chat",
            "voice_text_to_speech": "/api/v1/voice/text-to-speech",
            "voice_realtime_ws": "ws://localhost:8000/api/v1/voice/transcribe-realtime",
            "sync_listings": "/api/v1/sync/listings",
            "sync_property_pdfs": "/api/v1/sync/property-pdfs",
            "sync_generic_pdfs": "/api/v1/sync/generic-pdfs",
            "sync_status": "/api/v1/sync/status",
            "admin_listing_summary": "/api/v1/admin/listings/{listing_id}/summary",
            "admin_summaries_generate": "/api/v1/admin/summaries/generate",
            "admin_cron_status": "/api/v1/admin/cron/status",
            "docs": "/docs",
            "redoc": "/redoc"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

