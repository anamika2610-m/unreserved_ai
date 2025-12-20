#!/bin/bash

# Quick start script for Property Chat API
# Usage: ./run_api.sh

echo "🚀 Starting Property Chat API..."
echo ""

# Activate virtual environment
if [ -d "myenv" ]; then
    echo "✓ Activating virtual environment..."
    source myenv/bin/activate
else
    echo "❌ Virtual environment not found. Please run:"
    echo "   python3 -m venv myenv"
    echo "   source myenv/bin/activate"
    echo "   pip install -r requirements.txt"
    exit 1
fi

# Check if vector store exists
if [ ! -d "chroma_db" ]; then
    echo "⚠️  Warning: Vector store not found!"
    echo "   Run: python scripts/initialize_vector_store.py"
    echo ""
fi

# Check if .env exists with GROQ_API_KEY
if [ ! -f ".env" ]; then
    echo "⚠️  Warning: .env file not found!"
    echo "   Create .env with: GROQ_API_KEY=your_key_here"
    echo ""
fi

# Start the API server
echo "✓ Starting API server on http://localhost:8000"
echo ""
echo "📖 API Documentation: http://localhost:8000/docs"
echo "🔄 ReDoc: http://localhost:8000/redoc"
echo ""
echo "Press Ctrl+C to stop the server"
echo "=" * 70
echo ""

uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000

