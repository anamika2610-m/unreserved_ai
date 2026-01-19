from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Note: PropertyEmbedding model is defined in app.ingestion_pipeline.pgvector_store
# Alembic will discover it through the imports in pgvector_store.py
# No need to import it here (causes circular import)

