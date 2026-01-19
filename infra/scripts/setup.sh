#!/bin/bash

# Setup script for Unreserved project

echo "Setting up Unreserved project..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Initialize Alembic (if not already done)
if [ ! -d "alembic/versions" ]; then
    echo "Creating Alembic versions directory..."
    mkdir -p alembic/versions
    touch alembic/versions/.gitkeep
fi

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Activate the virtual environment: source venv/bin/activate"
echo "2. If you have an existing database, run: python tests/unit/reflect_schema.py"
echo "3. Create your SQLAlchemy models in app/db/models/"
echo "4. Create your first migration: alembic revision --autogenerate -m 'initial schema'"
echo "5. Review the migration file, then apply: alembic upgrade head"
echo "6. Run the FastAPI app: uvicorn app.main:app --reload"

