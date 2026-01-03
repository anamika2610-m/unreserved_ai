"""
FastAPI application for Property Chat API.

Run with:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    
Or:
    python -m uvicorn app.main:app --reload
"""

import os

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.routes.chat import router as chat_router
from app.api.v1.routes.sync import router as sync_router

app = FastAPI(
    title="Unreserved Property Chat API",
    description="RESTful API for conversational property listing queries",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)  
app.include_router(sync_router)  


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "service": "Unreserved Property Chat API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "chat": "/api/v1/chat/message",
            "chat_health": "/api/v1/chat/health",
            "sync_trigger": "/api/v1/sync/trigger",
            "sync_status": "/api/v1/sync/status",
            "docs": "/docs",
            "redoc": "/redoc"
        }
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

