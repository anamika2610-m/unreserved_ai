"""
PostgreSQL pgvector-based vector store for property listings.
Uses OpenAI embeddings for semantic search.
"""
import os
import time
from typing import List, Dict, Any, Optional
from decimal import Decimal
from sqlalchemy import text, Column, String, Integer, Text, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from pgvector.sqlalchemy import Vector

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.helpers.ingestion_pipeline.shared.chunker import Chunk
from app.helpers.ingestion_pipeline.shared.openai_embeddings import OpenAIEmbeddings, VECTOR_DIMENSION


class PropertyEmbedding(Base):
    """
    SQLAlchemy model for storing property listing embeddings.
    Uses pgvector extension for efficient similarity search.
    """
    __tablename__ = "property_embeddings"
    
    # NOTE:
    # In some databases this column is created as UUID. We model it as UUID here
    # and use a separate logical key (listing_id + chunk_type + chunk_index)
    # instead of overloading `id` with a composite string.
    id = Column(UUID(as_uuid=False), primary_key=True)
    listing_id = Column(String, nullable=False, index=True)
    chunk_type = Column(String, nullable=False, index=True)  # overview, pricing, specifications, location, bidding
    chunk_index = Column(Integer, nullable=False)
    
    content = Column(Text, nullable=False)
    
    embedding = Column(Vector(VECTOR_DIMENSION), nullable=False)
    
    chunk_metadata = Column('metadata', JSONB, nullable=True)
    
    __table_args__ = (
        Index('idx_listing_id', 'listing_id'),
        Index('idx_chunk_type', 'chunk_type'),
        Index(
            'idx_embedding_cosine',
            'embedding',
            postgresql_using='ivfflat',
            postgresql_with={'lists': 100},
            postgresql_ops={'embedding': 'vector_cosine_ops'}
        ),
    )


class PgVectorStore:
    """
    PostgreSQL + pgvector implementation of vector store.
    Stores property listing embeddings for semantic search.
    """
    
    def __init__(
        self,
        embedding_model: str = "text-embedding-3-small",
        db_session: Optional[Session] = None,
        openai_api_key: Optional[str] = None
    ):
        """
        Initialize pgvector store with OpenAI embeddings.
        
        Args:
            embedding_model: OpenAI embedding model name (default: text-embedding-3-small)
            db_session: Optional database session (creates new one if not provided)
            openai_api_key: Optional OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self.embedding_model_name = embedding_model
        self.db_session = db_session
        self._owns_session = False
        
        print(f"Initializing OpenAI embeddings with model: {embedding_model}")
        try:
            # Try to get API key from parameter, env var, or .env file
            if not openai_api_key:
                openai_api_key = os.getenv("OPENAI_API_KEY")
            
            # If still not found, try loading from .env file
            if not openai_api_key:
                try:
                    from dotenv import load_dotenv
                    load_dotenv()
                    openai_api_key = os.getenv("OPENAI_API_KEY")
                except ImportError:
                    pass
            
            self.embedding_model = OpenAIEmbeddings(api_key=openai_api_key, model=embedding_model)
            print(f"✓ OpenAI embeddings initialized successfully")
        except Exception as e:
            print(f"✗ Failed to initialize OpenAI embeddings: {e}")
            raise RuntimeError(f"Cannot initialize OpenAI embeddings: {e}")
        
        if self.db_session is None:
            try:
                self.db_session = SessionLocal()
                self._owns_session = True
            except Exception as e:
                print(f"⚠️  Initial DB connection warning: {e}")
                time.sleep(1)
                self.db_session = SessionLocal()
                self._owns_session = True
        
        self._initialize_pgvector()
    
    def _initialize_pgvector(self):
        """Initialize pgvector extension and create tables with retry logic."""
        max_retries = 3
        base_delay = 1
        
        for attempt in range(max_retries):
            try:
                self.db_session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                self.db_session.commit()
                print("✓ pgvector extension enabled")
                
                Base.metadata.create_all(bind=engine, tables=[PropertyEmbedding.__table__])
                print("✓ property_embeddings table ready")
                return
                
            except OperationalError as e:
                if attempt < max_retries - 1:
                    retry_delay = base_delay * (2 ** attempt)
                    print(f"⚠️  Connection issue (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    if self._owns_session:
                        try:
                            self.db_session.close()
                        except:
                            pass
                        self.db_session = SessionLocal()
                else:
                    print(f"⚠️  Warning: {e}")
                    try:
                        self.db_session.rollback()
                    except:
                        pass
            except Exception as e:
                print(f"⚠️  Warning: {e}")
                try:
                    self.db_session.rollback()
                except:
                    pass
                break
    
    def _sanitize_metadata(self, value: Any) -> Any:
        """
        Recursively sanitize metadata to ensure JSON serializability.
        Converts UUIDs, Decimals, and other non-JSON types to strings/numbers.
        """
        import uuid
        from decimal import Decimal
        
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, Decimal):
            return float(value)
        """
        Recursively sanitize metadata so it is JSON-serializable.
        
        Converts Decimal -> float, and processes dicts/lists recursively.
        """
        if isinstance(value, Decimal):
            # Use float for numeric values; if you prefer strings, change to str(value)
            return float(value)
        if isinstance(value, dict):
            return {k: self._sanitize_metadata(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._sanitize_metadata(v) for v in value]
        return value
    
    def add_chunks(self, chunks: List[Chunk]) -> None:
        """
        Add property listing chunks to vector store.
        
        Args:
            chunks: List of Chunk objects to embed and store
        """
        if not chunks:
            print("No chunks to add")
            return
        
        print(f"Adding {len(chunks)} chunks to vector store...")
        
        print("Generating embeddings using OpenAI...")
        texts = [chunk.content for chunk in chunks]
        embeddings = self.embedding_model.encode(
            texts,
            show_progress_bar=True,
            convert_to_numpy=True
        )
        
        # Convert numpy arrays to lists for storage
        embeddings = [emb.tolist() if hasattr(emb, 'tolist') else emb for emb in embeddings]
        
        print("Storing in PostgreSQL...")
        added_count = 0
        updated_count = 0
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                for chunk, embedding in zip(chunks, embeddings):
                    # Logical key for upserts: (listing_id, chunk_type, chunk_index)
                    listing_id_str = str(chunk.listing_id)

                    existing = (
                        self.db_session.query(PropertyEmbedding)
                        .filter(
                            PropertyEmbedding.listing_id == listing_id_str,
                            PropertyEmbedding.chunk_type == chunk.chunk_type,
                            PropertyEmbedding.chunk_index == chunk.chunk_index,
                        )
                        .first()
                    )
                    
                    # Sanitize metadata to avoid non-JSON-serializable types (e.g. Decimal)
                    sanitized_metadata = self._sanitize_metadata(chunk.metadata) if chunk.metadata is not None else None
                    
                    # Ensure embedding is a list (not numpy array)
                    embedding_list = embedding.tolist() if hasattr(embedding, 'tolist') else embedding
                    
                    if existing:
                        existing.content = chunk.content
                        existing.embedding = embedding_list
                        existing.chunk_metadata = sanitized_metadata
                        updated_count += 1
                    else:
                        import uuid

                        new_embedding = PropertyEmbedding(
                            id=str(uuid.uuid4()),
                            listing_id=listing_id_str,
                            chunk_type=chunk.chunk_type,
                            chunk_index=chunk.chunk_index,
                            content=chunk.content,
                            embedding=embedding_list,
                            chunk_metadata=sanitized_metadata,
                        )
                        self.db_session.add(new_embedding)
                        added_count += 1
                
                self.db_session.commit()
                print(f"✓ Added {added_count} new chunks, updated {updated_count} existing chunks")
                break  # Success, exit retry loop
                
            except (OperationalError, Exception) as e:
                if attempt < max_retries - 1:
                    retry_delay = 1 * (2 ** attempt)
                    print(f"⚠️  Database error during commit (attempt {attempt + 1}/{max_retries}): {type(e).__name__}")
                    print(f"   Retrying in {retry_delay}s...")
                    try:
                        self.db_session.rollback()
                    except:
                        pass
                    if self._owns_session:
                        self._refresh_session()
                    time.sleep(retry_delay)
                    # Reset counters for retry
                    added_count = 0
                    updated_count = 0
                else:
                    print(f"❌ Failed to commit after {max_retries} attempts: {type(e).__name__}: {e}")
                    try:
                        self.db_session.rollback()
                    except:
                        pass
                    raise
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        listing_id: Optional[str] = None,
        chunk_types: Optional[List[str]] = None,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar chunks using cosine similarity.
        
        Args:
            query: Search query text
            n_results: Number of results to return
            listing_id: Optional filter by listing ID (deprecated, use filter_metadata)
            chunk_types: Optional filter by chunk types (deprecated, use filter_metadata)
            filter_metadata: Optional metadata filters (ChromaDB compatibility)
            
        Returns:
            List of matching chunks with metadata and similarity scores
        """
        if filter_metadata:
            listing_id = listing_id or filter_metadata.get('listing_id')
            chunk_type_single = filter_metadata.get('chunk_type')
            if chunk_type_single and not chunk_types:
                chunk_types = [chunk_type_single]
        
        # Generate query embedding
        query_embeddings = self.embedding_model.encode([query], convert_to_numpy=False)
        query_embedding = query_embeddings[0] if query_embeddings else []
        
        sql = text("""
            SELECT 
                id,
                listing_id,
                chunk_type,
                chunk_index,
                content,
                metadata,
                1 - (embedding <=> CAST(:query_embedding AS vector)) as similarity
            FROM property_embeddings
            WHERE 1=1
            {listing_filter}
            {chunk_type_filter}
            ORDER BY embedding <=> CAST(:query_embedding AS vector)
            LIMIT :n_results
        """.format(
            listing_filter="AND listing_id = :listing_id" if listing_id else "",
            chunk_type_filter="AND chunk_type = ANY(:chunk_types)" if chunk_types else ""
        ))
        
        # Ensure query_embedding is a list
        query_embedding_list = query_embedding.tolist() if hasattr(query_embedding, 'tolist') else query_embedding
        
        params = {
            'query_embedding': query_embedding_list,
            'n_results': n_results
        }
        if listing_id:
            # Convert UUID to string since property_embeddings.listing_id is VARCHAR
            params['listing_id'] = str(listing_id) if listing_id else None
        if chunk_types:
            params['chunk_types'] = chunk_types
        
        max_retries = 3
        rows = []
        for attempt in range(max_retries):
            try:
                result = self.db_session.execute(sql, params)
                rows = result.fetchall()
                break
            except OperationalError as e:
                if attempt < max_retries - 1:
                    retry_delay = 1 * (2 ** attempt)
                    print(f"⚠️  Database connection issue (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    try:
                        self.db_session.rollback()
                    except:
                        pass
                    if self._owns_session:
                        self._refresh_session()
                else:
                    print(f"❌ Connection failed after {max_retries} attempts. Please check your database connection.")
                    raise
            except Exception as e:
                # Catch any other errors (like InFailedSqlTransaction)
                print(f"⚠️  Database error: {type(e).__name__}: {e}")
                try:
                    self.db_session.rollback()
                except:
                    pass
                if self._owns_session and attempt < max_retries - 1:
                    self._refresh_session()
                    retry_delay = 1 * (2 ** attempt)
                    print(f"⚠️  Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    raise
        
        results = []
        for row in rows:
            similarity = float(row[6])
            results.append({
                'id': row[0],
                'listing_id': row[1],
                'chunk_type': row[2],
                'chunk_index': row[3],
                'content': row[4],
                'metadata': row[5],  
                'similarity': similarity,
                'distance': 1.0 - similarity  
            })
        
        return results
    
    def get_by_listing_id(self, listing_id: str) -> List[Dict[str, Any]]:
        """
        Get all chunks for a specific listing.
        
        Args:
            listing_id: Listing ID to retrieve chunks for
            
        Returns:
            List of all chunks for the listing
        """
        embeddings = self.db_session.query(PropertyEmbedding).filter(
            PropertyEmbedding.listing_id == str(listing_id)
        ).order_by(PropertyEmbedding.chunk_index).all()
        
        return [
            {
                'id': emb.id,
                'listing_id': emb.listing_id,
                'chunk_type': emb.chunk_type,
                'chunk_index': emb.chunk_index,
                'content': emb.content,
                'metadata': emb.chunk_metadata
            }
            for emb in embeddings
        ]
    
    def get_property_location(self, listing_id: str) -> Optional[Dict[str, Any]]:
        """
        Get location information for a specific listing.
        
        Args:
            listing_id: Listing ID to retrieve location for
            
        Returns:
            Dictionary with latitude, longitude, and address, or None if not found
        """
        embedding = self.db_session.query(PropertyEmbedding).filter(
            PropertyEmbedding.listing_id == str(listing_id)
        ).first()
        
        if not embedding or not embedding.chunk_metadata:
            return None
        
        metadata = embedding.chunk_metadata
        
        latitude = metadata.get('latitude')
        longitude = metadata.get('longitude')
        address = metadata.get('location') or metadata.get('address', '')
        
        if latitude is not None and longitude is not None:
            return {
                'latitude': float(latitude),
                'longitude': float(longitude),
                'address': address
            }
        
        return None
    
    def get_all_chunks(self) -> Dict[str, Any]:
        """
        Get all chunks in the database (for nearby property search).
        Returns data in a format compatible with ChromaDB's collection.get().
        
        Returns:
            Dictionary with 'ids', 'documents', and 'metadatas' keys
        """
        embeddings = self.db_session.query(PropertyEmbedding).all()
        
        return {
            'ids': [emb.id for emb in embeddings],
            'documents': [emb.content for emb in embeddings],
            'metadatas': [emb.chunk_metadata for emb in embeddings]
        }
    
    def delete_by_listing_id(self, listing_id: str) -> int:
        """
        Delete all chunks for a specific listing.
        
        Args:
            listing_id: Listing ID to delete chunks for
            
        Returns:
            Number of chunks deleted
        """
        count = self.db_session.query(PropertyEmbedding).filter(
            PropertyEmbedding.listing_id == str(listing_id)
        ).delete()
        self.db_session.commit()
        return count
    
    def clear_all(self) -> None:
        """
        Delete ALL embeddings from the database.
        
        ⚠️  WARNING: This will delete EVERYTHING including property_document chunks!
        Only use this if you want to completely reset the vector store.
        For normal syncing, use add_chunks() which handles incremental updates automatically.
        """
        self.db_session.query(PropertyEmbedding).delete()
        self.db_session.commit()
        print("⚠️  All embeddings cleared (including property_document chunks)")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the vector store.
        
        Returns:
            Dictionary with stats
        """
        total_chunks = self.db_session.query(PropertyEmbedding).count()
        
        unique_listings = self.db_session.execute(
            text("SELECT COUNT(DISTINCT listing_id) FROM property_embeddings")
        ).scalar()
        
        chunk_type_counts = self.db_session.execute(
            text("""
                SELECT chunk_type, COUNT(*) as count
                FROM property_embeddings
                GROUP BY chunk_type
                ORDER BY count DESC
            """)
        ).fetchall()
        
        return {
            'total_chunks': total_chunks,
            'unique_listings': unique_listings or 0,
            'chunk_types': {row[0]: row[1] for row in chunk_type_counts},
            'embedding_model': self.embedding_model_name,
            'vector_dimension': VECTOR_DIMENSION
        }
    
    def _refresh_session(self):
        """Refresh the database session if it's stale."""
        if self._owns_session and self.db_session:
            try:
                self.db_session.close()
            except:
                pass
            try:
                engine.dispose()
            except:
                pass
            self.db_session = SessionLocal()
    
    def close(self):
        """Close database session if owned by this instance."""
        if self._owns_session and self.db_session:
            try:
                self.db_session.close()
            except:
                pass
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

