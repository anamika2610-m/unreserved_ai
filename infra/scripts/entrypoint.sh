#!/bin/bash
# Container entrypoint script for Unreserved API

set -e

echo "🚀 Starting Unreserved Property Chat API..."
echo ""

# Check if vector store exists, initialize if not
if [ ! -d "/app/chroma_db" ] || [ -z "$(ls -A /app/chroma_db 2>/dev/null)" ]; then
    echo "⚠️  Vector store not found or empty. Initializing..."
    python tests/unit/initialize_vector_store.py || {
        echo "❌ Failed to initialize vector store. Continuing anyway..."
    }
    echo ""
fi

# Check for required environment variables
if [ -z "$OPENAI_API_KEY" ]; then
    echo "⚠️  Warning: OPENAI_API_KEY is not set!"
    echo "   The API will start but chat endpoints will fail."
    echo ""
fi

# Get port from environment or use default
PORT=${PORT:-8000}

echo "✓ Starting API server on port ${PORT}"
echo "📖 API Documentation: http://localhost:${PORT}/docs"
echo "🔄 ReDoc: http://localhost:${PORT}/redoc"
echo ""

# Execute the main command (CMD arguments are passed as $@)
exec "$@"

