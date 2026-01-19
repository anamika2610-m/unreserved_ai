#!/bin/bash

# Quick start script for Property Chat API
# Usage: ./run_api.sh

echo "🚀 Starting Property Chat API..."
echo ""

# Activate virtual environment
if [ -d "venv" ]; then
    echo "✓ Activating virtual environment..."
    source venv/bin/activate
else
    echo "❌ Virtual environment not found. Please run:"
    echo "   python3 -m venv venv"
    echo "   source venv/bin/activate"
    echo "   pip install -r requirements.txt"
    exit 1
fi

# Check if vector store exists
if [ ! -d "chroma_db" ]; then
    echo "⚠️  Warning: Vector store not found!"
    echo "   Run: python tests/unit/initialize_vector_store.py"
    echo ""
fi

# Check if .env exists with OPENAI_API_KEY
if [ ! -f ".env" ]; then
    echo "⚠️  Warning: .env file not found!"
    echo "   Create .env with: OPENAI_API_KEY=your_key_here"
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

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

