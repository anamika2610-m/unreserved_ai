"""
PostgreSQL pgvector-based vector store for property listings.
Uses OpenAI embeddings for semantic search.
"""
import logging
import os
import time
from decimal import Decimal
from typing import List, Dict, Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import text, Column, String, Integer, Text, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.helpers.ingestion_pipeline.shared.chunker import Chunk
from app.helpers.ingestion_pipeline.shared.openai_embeddings import (
    OpenAIEmbeddings,
    VECTOR_DIMENSION,
)


logger = logging.getLogger(__name__)


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

        logger.info("Initializing OpenAI embeddings with model: %s", embedding_model)
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
            
            self.embedding_model = OpenAIEmbeddings(
                api_key=openai_api_key,
                model=embedding_model,
            )
            logger.info("✓ OpenAI embeddings initialized successfully")
        except Exception as e:
            logger.exception("✗ Failed to initialize OpenAI embeddings: %s", e)
            raise RuntimeError(f"Cannot initialize OpenAI embeddings: {e}") from e
        
        if self.db_session is None:
            try:
                self.db_session = SessionLocal()
                self._owns_session = True
            except Exception as e:
                logger.warning("⚠️  Initial DB connection warning: %s", e)
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
                logger.info("✓ pgvector extension enabled")

                Base.metadata.create_all(bind=engine, tables=[PropertyEmbedding.__table__])
                logger.info("✓ property_embeddings table ready")
                return
                
            except OperationalError as e:
                if attempt < max_retries - 1:
                    retry_delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "⚠️  Connection issue (attempt %s/%s), retrying in %ss...",
                        attempt + 1,
                        max_retries,
                        retry_delay,
                    )
                    time.sleep(retry_delay)
                    if self._owns_session:
                        try:
                            self.db_session.close()
                        except:
                            pass
                        self.db_session = SessionLocal()
                else:
                    logger.warning("⚠️  Warning: %s", e)
                    try:
                        self.db_session.rollback()
                    except:
                        pass
            except Exception as e:
                logger.warning("⚠️  Warning: %s", e)
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
    
    def add_chunks(
        self,
        chunks: List[Chunk],
        db_doc_info: Optional[Dict[str, Dict]] = None
    ) -> None:
        """
        Add property listing chunks to vector store.
        
        Args:
            chunks: List of Chunk objects to embed and store
            db_doc_info: Optional dict of doc_id -> {total_chunks}
                        If provided, will sync with DB state (delete stale chunks).
        """
        if not chunks:
            logger.info("No chunks to add")
            return

        logger.info("Adding %d chunks to vector store...", len(chunks))

        logger.info("Generating embeddings using OpenAI...")
        # Strip NUL bytes from chunk content – PostgreSQL TEXT fields reject \x00
        for chunk in chunks:
            if chunk.content:
                chunk.content = chunk.content.replace('\x00', '')
        texts = [chunk.content for chunk in chunks]
        embeddings = self.embedding_model.encode(
            texts,
            show_progress_bar=True,
            convert_to_numpy=True
        )
        
        # Convert numpy arrays to lists for storage
        embeddings = [emb.tolist() if hasattr(emb, 'tolist') else emb for emb in embeddings]

        logger.info("Storing in PostgreSQL...")
        
        if db_doc_info is not None and chunks:
            logger.info("Starting chunk sync for %d listings", len(set(c.listing_id for c in chunks if c.listing_id)))
            self._sync_chunks_with_db(chunks, db_doc_info)
        
        added_count = 0
        updated_count = 0
        listings_touched = set()

        max_retries = 3
        for attempt in range(max_retries):
            try:
                for chunk, embedding in zip(chunks, embeddings):
                    # Logical key for upserts: (listing_id, chunk_type, chunk_index)
                    listing_id_str = str(chunk.listing_id)
                    listings_touched.add(listing_id_str)

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
                        logger.debug(
                            "Embedding updated: listing_id=%s chunk_type=%s chunk_index=%s",
                            listing_id_str, chunk.chunk_type, chunk.chunk_index,
                        )
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
                        logger.debug(
                            "Embedding created: listing_id=%s chunk_type=%s chunk_index=%s",
                            listing_id_str, chunk.chunk_type, chunk.chunk_index,
                        )
                
                self.db_session.commit()
                logger.info(
                    "✓ Added %d new chunks, updated %d existing chunks",
                    added_count,
                    updated_count,
                )
                
                list_preview = sorted(listings_touched)[:20]
                if len(listings_touched) > 20:
                    list_preview.append("...")
                logger.info(
                    "[EMBED] property_embeddings: created=%d updated=%d listings=%s",
                    added_count, updated_count, list_preview,
                )
                break  # Success, exit retry loop
                
            except (OperationalError, Exception) as e:
                if attempt < max_retries - 1:
                    retry_delay = 1 * (2 ** attempt)
                    logger.warning(
                        "⚠️  Database error during commit (attempt %s/%s): %s",
                        attempt + 1,
                        max_retries,
                        type(e).__name__,
                    )
                    logger.warning("   Retrying in %ss...", retry_delay)
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
                    logger.exception(
                        "❌ Failed to commit after %s attempts: %s: %s",
                        max_retries,
                        type(e).__name__,
                        e,
                    )
                    try:
                        self.db_session.rollback()
                    except:
                        pass
                    raise
    
    def _sync_chunks_with_db(
        self,
        chunks: List[Chunk],
        db_doc_info: Dict[str, Dict]
    ) -> None:
        """
        Sync chunks with DB state:
        - Delete all existing property_document chunks for each listing first
        - Then add fresh chunks from DB
        
        This ensures complete sync: any docs not in DB are removed, any new docs are added.
        
        Args:
            chunks: The chunks being synced
            db_doc_info: Dict of doc_id -> {total_chunks} from DB
        """
        if not chunks:
            logger.info("_sync_chunks_with_db: chunks is empty, returning")
            return
        
        listing_ids = set()
        for chunk in chunks:
            if chunk.listing_id:
                listing_ids.add(str(chunk.listing_id))
        
        if not listing_ids:
            logger.info("_sync_chunks_with_db: no listing_ids found, returning")
            return
        
        logger.info("_sync_chunks_with_db: processing listings %s", list(listing_ids))
        
        for listing_id in listing_ids:
            try:
                logger.info("_sync_chunks_with_db: checking listing %s for existing property_document chunks", listing_id)
                deleted_count = (
                    self.db_session.query(PropertyEmbedding)
                    .filter(
                        PropertyEmbedding.listing_id == listing_id,
                        PropertyEmbedding.chunk_type == "property_document"
                    )
                    .delete(synchronize_session=False)
                )
                logger.info("_sync_chunks_with_db: found %d existing chunks for listing %s", deleted_count, listing_id)
                self.db_session.commit()
                print(f"DEBUG: _sync_chunks_with_db - COMMIT SUCCESS for listing {listing_id}")
                if deleted_count > 0:
                    print(f"DEBUG: Deleted {deleted_count} existing chunks for listing {listing_id} before re-sync")
                    logger.info(
                        "Deleted %d existing chunks for listing %s before re-sync",
                        deleted_count, listing_id
                    )
            except Exception as e:
                logger.warning("Failed to delete existing chunks: %s", e)
                try:
                    self.db_session.rollback()
                except:
                    pass
    
    def _cleanup_orphan_chunks(self, chunks: List[Chunk], valid_doc_ids: List[str]) -> None:
        """
        Legacy method - redirects to _sync_chunks_with_db with minimal info.
        """
        if not chunks or not valid_doc_ids:
            return
        
        db_doc_info = {str(doc_id): {} for doc_id in valid_doc_ids if doc_id}
        self._sync_chunks_with_db(chunks, db_doc_info)
    
    def get_existing_doc_ids(self, listing_id: str) -> Dict[str, Dict]:
        """
        Get all existing doc_ids and their info from vector store for a listing.
        
        Returns:
            Dict of doc_id -> {chunk_indices}
        """
        existing_chunks = (
            self.db_session.query(PropertyEmbedding)
            .filter(
                PropertyEmbedding.listing_id == listing_id,
                PropertyEmbedding.chunk_type == "property_document"
            )
            .all()
        )
        
        doc_info = {}
        for chunk in existing_chunks:
            doc_id = chunk.chunk_metadata.get("doc_id") if chunk.chunk_metadata else None
            if doc_id:
                if doc_id not in doc_info:
                    doc_info[doc_id] = {
                        "chunk_indices": []
                    }
                doc_info[doc_id]["chunk_indices"].append(chunk.chunk_index)
        
        return doc_info
    
    def sync_property_documents(
        self,
        listing_id: str,
        chunks: List[Chunk],
        db_doc_info: Dict[str, Dict]
    ) -> Dict[str, int]:
        """
        Efficient sync using list comparison:
        1. Get existing doc_ids from vector store
        2. Compare with DB doc_ids
        3. Delete orphaned docs (in vector store but not DB)
        4. Add new docs (not in vector store)
        
        Returns:
            Dict with counts: {added, updated, deleted, skipped}
        """
        logger.info(f"🔄 [SYNC] Starting sync for listing {listing_id}")
        
        # Step 1: Get existing doc_ids from vector store
        existing_doc_info = self.get_existing_doc_ids(listing_id)
        existing_doc_ids = set(existing_doc_info.keys())
        logger.info(f"📋 [SYNC] Found {len(existing_doc_ids)} existing docs in vector store: {existing_doc_ids}")
        
        # Step 2: Get doc_ids from DB (chunks)
        new_doc_ids = set()
        chunks_by_doc = {}
        for chunk in chunks:
            doc_id = chunk.metadata.get("doc_id") if chunk.metadata else None
            if doc_id:
                new_doc_ids.add(str(doc_id))
                if str(doc_id) not in chunks_by_doc:
                    chunks_by_doc[str(doc_id)] = []
                chunks_by_doc[str(doc_id)].append(chunk)
        
        logger.info(f"📋 [SYNC] DB has {len(new_doc_ids)} docs: {new_doc_ids}")
        logger.info(f"📋 [SYNC] Vector store has {len(existing_doc_ids)} docs")
        
        # Step 3: Find orphaned docs (in vector store but NOT in DB).
        # Use db_doc_info.keys() (all doc_ids from property_media) rather than
        # new_doc_ids (only docs that successfully extracted this run). This prevents
        # transient extraction failures from incorrectly deleting existing chunks.
        db_doc_ids = set(db_doc_info.keys()) if db_doc_info else new_doc_ids
        orphans = existing_doc_ids - db_doc_ids
        deleted_count = 0
        skipped_count = 0
        
        if orphans:
            logger.info(f"🗑️  [SYNC] Found {len(orphans)} orphan docs (deleted from DB): {orphans}")
            try:
                deleted_count = (
                    self.db_session.query(PropertyEmbedding)
                    .filter(
                        PropertyEmbedding.listing_id == listing_id,
                        PropertyEmbedding.chunk_type == "property_document",
                        PropertyEmbedding.chunk_metadata['doc_id'].astext.in_(list(orphans))
                    )
                    .delete(synchronize_session=False)
                )
                self.db_session.commit()
                logger.info(f"✅ [SYNC] Deleted {deleted_count} orphan chunks")
            except Exception as e:
                logger.warning("Failed to delete orphan chunks: %s", e)
                self.db_session.rollback()
        else:
            logger.info("✅ [SYNC] No orphans to delete")
        
        # Step 4: Add new docs - filter chunks to only add new docs
        docs_to_add = []
        new_count = 0
        unchanged_count = 0
        
        for doc_id in new_doc_ids:
            if doc_id not in existing_doc_ids:
                # New doc - add all chunks
                new_count += 1
                docs_to_add.extend(chunks_by_doc[doc_id])
            else:
                # Already exists - skip (smart sync handles doc replacement via orphan detection)
                unchanged_count += 1
        
        logger.info(f"📊 [SYNC] Docs status - New: {new_count}, Unchanged: {unchanged_count}")
        
        if docs_to_add:
            self._add_chunks_to_store(docs_to_add, listing_id)
        
        logger.info(f"✅ [SYNC] Sync complete - Added: {len(docs_to_add)}, Deleted: {deleted_count}, Skipped: {unchanged_count}")
        
        return {
            "added": len(docs_to_add),
            "updated": 0,
            "deleted": deleted_count,
            "skipped": unchanged_count
        }
    
    def _add_chunks_to_store(self, chunks: List[Chunk], listing_id: str) -> None:
        """Helper method to embed and add chunks to the database."""
        if not chunks:
            return
        
        logger.info("Generating embeddings for %d chunks...", len(chunks))
        
        for chunk in chunks:
            if chunk.content:
                chunk.content = chunk.content.replace('\x00', '')
        
        texts = [chunk.content for chunk in chunks]
        embeddings = self.embedding_model.encode(
            texts,
            show_progress_bar=True,
            convert_to_numpy=True
        )
        embeddings = [emb.tolist() if hasattr(emb, 'tolist') else emb for emb in embeddings]
        
        logger.info("Storing embeddings in PostgreSQL...")
        
        for chunk, embedding in zip(chunks, embeddings):
            embedding_list = embedding.tolist() if hasattr(embedding, 'tolist') else embedding
            chunk_index = chunk.chunk_index
            
            existing = (
                self.db_session.query(PropertyEmbedding)
                .filter(
                    PropertyEmbedding.listing_id == listing_id,
                    PropertyEmbedding.chunk_type == chunk.chunk_type,
                    PropertyEmbedding.chunk_index == chunk_index,
                )
                .first()
            )
            
            sanitized_metadata = self._sanitize_metadata(chunk.metadata) if chunk.metadata is not None else None
            
            if existing:
                existing.content = chunk.content
                existing.embedding = embedding_list
                existing.chunk_metadata = sanitized_metadata
            else:
                import uuid
                new_embedding = PropertyEmbedding(
                    id=str(uuid.uuid4()),
                    listing_id=listing_id,
                    chunk_type=chunk.chunk_type,
                    chunk_index=chunk_index,
                    content=chunk.content,
                    embedding=embedding_list,
                    chunk_metadata=sanitized_metadata,
                )
                self.db_session.add(new_embedding)
        
        self.db_session.commit()
        logger.info("Successfully added %d chunks to property_embeddings", len(chunks))
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        listing_id: Optional[str] = None,
        chunk_types: Optional[List[str]] = None,
        filter_metadata: Optional[Dict[str, Any]] = None,
        query_embedding: Optional[List[float]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for similar chunks using cosine similarity.
        
        Args:
            query: Search query text (used only when query_embedding is not provided)
            n_results: Number of results to return
            listing_id: Optional filter by listing ID (deprecated, use filter_metadata)
            chunk_types: Optional filter by chunk types (deprecated, use filter_metadata)
            filter_metadata: Optional metadata filters (ChromaDB compatibility)
            query_embedding: Optional precomputed query embedding to avoid repeated encode() calls
            
        Returns:
            List of matching chunks with metadata and similarity scores
        """
        if filter_metadata:
            listing_id = listing_id or filter_metadata.get('listing_id')
            chunk_type_single = filter_metadata.get('chunk_type')
            if chunk_type_single and not chunk_types:
                chunk_types = [chunk_type_single]
        
        # Use precomputed embedding when provided (saves embedding API calls when doing multiple searches)
        if query_embedding is not None:
            query_embedding_list = list(query_embedding)
        else:
            query_embeddings = self.embedding_model.encode([query], convert_to_numpy=False)
            raw = query_embeddings[0] if query_embeddings else []
            query_embedding_list = raw.tolist() if hasattr(raw, 'tolist') else list(raw)
        
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
        result = None
        for attempt in range(max_retries):
            try:
                # Execute query
                result = self.db_session.execute(sql, params)
                rows = result.fetchall()
                
                # Explicitly close the result immediately after fetching
                result.close()
                result = None
                
                # Commit the read transaction immediately to release locks
                # This prevents "idle in transaction" state
                self.db_session.commit()
            
            
                
                break
            except OperationalError as e:
                if result:
                    try:
                        result.close()
                        result = None
                    except:
                        pass
                if attempt < max_retries - 1:
                    retry_delay = 1 * (2 ** attempt)
                    logger.warning(
                        "⚠️  Database connection issue (attempt %s/%s), retrying in %ss...",
                        attempt + 1,
                        max_retries,
                        retry_delay,
                    )
                    time.sleep(retry_delay)
                    try:
                        self.db_session.rollback()
                    except:
                        pass
                    if self._owns_session:
                        self._refresh_session()
                else:
                    logger.exception(
                        "❌ Connection failed after %s attempts. Please check your database connection.",
                        max_retries,
                    )
                    raise
            except Exception as e:
                # Catch any other errors (like InFailedSqlTransaction)
                if result:
                    try:
                        result.close()
                        result = None
                    except:
                        pass
                logger.exception("⚠️  Database error: %s: %s", type(e).__name__, e)
                try:
                    self.db_session.rollback()
                except:
                    pass
                if self._owns_session and attempt < max_retries - 1:
                    self._refresh_session()
                    retry_delay = 1 * (2 ** attempt)
                    logger.warning("⚠️  Retrying in %ss...", retry_delay)
                    time.sleep(retry_delay)
                else:
                    raise
            finally:
                # Always ensure result is closed
                if result is not None:
                    try:
                        result.close()
                    except:
                        pass
                # Ensure transaction is committed or rolled back
                # Check if session is in a transaction and rollback if needed
                try:
                    # Try to check transaction state (SQLAlchemy 2.0+)
                    if hasattr(self.db_session, 'in_transaction'):
                        if self.db_session.in_transaction():
                            self.db_session.rollback()
                    elif hasattr(self.db_session, 'is_active'):
                        if self.db_session.is_active:
                            self.db_session.rollback()
                except:
                    pass
        
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
        try:
            embeddings = (
                self.db_session.query(PropertyEmbedding)
                .filter(PropertyEmbedding.listing_id == str(listing_id))
                .order_by(PropertyEmbedding.chunk_index)
                .all()
            )
            
            # Extract data BEFORE commit to prevent lazy-loading expired objects
            results = [
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
            
            # Commit to close the read transaction and prevent "idle in transaction"
            self.db_session.commit()
            
            return results
        except Exception:
            self.db_session.rollback()
            raise
    
    def get_property_location(self, listing_id: str) -> Optional[Dict[str, Any]]:
        """
        Get location information for a specific listing.
        
        Args:
            listing_id: Listing ID to retrieve location for
            
        Returns:
            Dictionary with latitude, longitude, and address, or None if not found
        """
        try:
            embedding = (
                self.db_session.query(PropertyEmbedding)
                .filter(PropertyEmbedding.listing_id == str(listing_id))
                .first()
            )
            
            if not embedding or not embedding.chunk_metadata:
                self.db_session.commit()
                return None
            
            # Extract data BEFORE commit
            metadata = embedding.chunk_metadata
            latitude = metadata.get('latitude')
            longitude = metadata.get('longitude')
            address = metadata.get('location') or metadata.get('address', '')
            
            # Commit to close the read transaction and prevent "idle in transaction"
            self.db_session.commit()
            
            if latitude is not None and longitude is not None:
                return {
                    'latitude': float(latitude),
                    'longitude': float(longitude),
                    'address': address
                }
            
            return None
        except Exception:
            self.db_session.rollback()
            raise
    
    def get_all_chunks(self) -> Dict[str, Any]:
        """
        Get all chunks in the database (for nearby property search).
        Returns data in a format compatible with ChromaDB's collection.get().
        
        Returns:
            Dictionary with 'ids', 'documents', and 'metadatas' keys
        """
        try:
            embeddings = self.db_session.query(PropertyEmbedding).all()
            
            # Extract data BEFORE commit
            results = {
                'ids': [emb.id for emb in embeddings],
                'documents': [emb.content for emb in embeddings],
                'metadatas': [emb.chunk_metadata for emb in embeddings]
            }
            
            # Commit to close the read transaction and prevent "idle in transaction"
            self.db_session.commit()
            
            return results
        except Exception:
            self.db_session.rollback()
            raise
    
    def delete_by_listing_id(self, listing_id: str) -> int:
        """
        Delete all chunks for a specific listing.
        
        Args:
            listing_id: Listing ID to delete chunks for
            
        Returns:
            Number of chunks deleted
        """
        try:
            count = self.db_session.query(PropertyEmbedding).filter(
                PropertyEmbedding.listing_id == str(listing_id)
            ).delete()
            self.db_session.commit()
            return count
        except Exception:
            self.db_session.rollback()
            raise
    
    def clear_all(self) -> None:
        """
        Delete ALL embeddings from the database.
        
        ⚠️  WARNING: This will delete EVERYTHING including property_document chunks!
        Only use this if you want to completely reset the vector store.
        For normal syncing, use add_chunks() which handles incremental updates automatically.
        """
        try:
            self.db_session.query(PropertyEmbedding).delete()
            self.db_session.commit()
            logger.warning("⚠️  All embeddings cleared (including property_document chunks)")
        except Exception:
            self.db_session.rollback()
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the vector store.
        
        Returns:
            Dictionary with stats
        """
        try:
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
            
            # Commit to close the read transaction and prevent "idle in transaction"
            self.db_session.commit()
            
            return {
                'total_chunks': total_chunks,
                'unique_listings': unique_listings or 0,
                'chunk_types': {row[0]: row[1] for row in chunk_type_counts},
                'embedding_model': self.embedding_model_name,
                'vector_dimension': VECTOR_DIMENSION
            }
        except Exception:
            self.db_session.rollback()
            raise
    
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

