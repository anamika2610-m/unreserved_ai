"""
FastAPI application for Property Chat API.

Run with:
    uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
    
Or:
    python -m uvicorn app.api.main:app --reload
"""

import os

# Disable ChromaDB telemetry and tokenizer warnings
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.chat import router as chat_router

# Create FastAPI app
app = FastAPI(
    title="Unreserved Property Chat API",
    description="RESTful API for conversational property listing queries",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(chat_router)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "service": "Unreserved Property Chat API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "chat": "/api/chat/message",
            "health": "/api/chat/health",
            "docs": "/docs",
            "redoc": "/redoc"
        }
    }


# Health check at root level
@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

