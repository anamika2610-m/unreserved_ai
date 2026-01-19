# Multi-stage Dockerfile for Unreserved Property Chat API
# Compatible with both Docker and Podman

# Stage 1: Base image with Python
FROM python:3.11-slim as base

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ANONYMIZED_TELEMETRY=False \
    TOKENIZERS_PARALLELISM=false

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Stage 2: Dependencies
FROM base as dependencies

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Stage 3: Production image
FROM base as production

# Copy installed dependencies from dependencies stage
COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=dependencies /usr/local/bin /usr/local/bin

# Copy application code
COPY app/ ./app/
COPY tests/ ./tests/
COPY alembic.ini ./
COPY alembic/ ./alembic/

# Copy entrypoint script (before switching user so we can set permissions)
COPY infra/scripts/entrypoint.sh ./entrypoint.sh
RUN chmod +x entrypoint.sh

# Note: No persistent data directories needed - using PostgreSQL with pgvector
# All data is stored in the database

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port (can be overridden via environment variable)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Use entrypoint script
ENTRYPOINT ["./entrypoint.sh"]

# Default command (can be overridden)
# Use shell form to allow PORT env var expansion
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}

