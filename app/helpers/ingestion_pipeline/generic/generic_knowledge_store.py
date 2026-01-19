"""
Generic Knowledge Vector Store - Separate from property-specific embeddings
Stores generic PDFs like legislation, buyer guides, auction rules, etc.
Uses OpenAI embeddings for semantic search.
"""
import json
from contextlib import contextmanager
from decimal import Decimal
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.helpers.ingestion_pipeline.shared.openai_embeddings import OpenAIEmbeddings, VECTOR_DIMENSION


@dataclass
class GenericChunk:
    """Represents a chunk of generic knowledge"""
    content: str
    doc_category: str
    chunk_index: int
    metadata: Dict[str, Any]


class GenericKnowledgeStore:
    """
    Vector store for generic knowledge base.
    Completely separate from property-specific embeddings.
    """
    
    def __init__(
        self, 
        embedding_model: str = "text-embedding-3-small",
        db_session: Optional[Session] = None,
        openai_api_key: Optional[str] = None
    ):
        """
        Initialize generic knowledge store with OpenAI embeddings.
        
        Args:
            embedding_model: OpenAI embedding model name (default: text-embedding-3-small)
            db_session: Optional database session
            openai_api_key: Optional OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        print(f"Initializing Generic Knowledge Store with OpenAI embeddings: {embedding_model}")
        try:
            self.embedding_model = OpenAIEmbeddings(api_key=openai_api_key, model=embedding_model)
            print("✓ Generic Knowledge Store initialized with OpenAI embeddings")
        except Exception as e:
            print(f"✗ Failed to initialize OpenAI embeddings: {e}")
            raise RuntimeError(f"Cannot initialize OpenAI embeddings: {e}")
        
        self.db_session = db_session or SessionLocal()
        self._owns_session = db_session is None
    
    @contextmanager
    def _handle_errors(self):
        """
        Context manager for automatic error handling and rollback.
        
        Usage:
            with self._handle_errors():
                # database operations
        """
        try:
            yield
        except SQLAlchemyError as e:
            self.db_session.rollback()
            raise e
    
    def _convert_embedding_to_list(self, embedding: Any) -> List[float]:
        """
        Convert embedding to list format (handles numpy arrays, lists, etc.).
        
        Args:
            embedding: Embedding in any format (numpy array, list, etc.)
            
        Returns:
            List of floats
        """
        if hasattr(embedding, 'tolist'):
            return embedding.tolist()
        return embedding if isinstance(embedding, list) else list(embedding)
    
    def initialize_table(self):
        """
        Create generic_knowledge table if it doesn't exist.
        
        Creates the table, indexes, and vector extension.
        For small datasets, skips ivfflat index (uses sequential scan).
        """
        try:
            with self._handle_errors():
                # Create vector extension
                self.db_session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                
                # Create table with updated vector dimension
                create_table_sql = text(f"""
                    CREATE TABLE IF NOT EXISTS generic_knowledge (
                        id VARCHAR PRIMARY KEY,
                        doc_category VARCHAR NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        embedding vector({VECTOR_DIMENSION}) NOT NULL,
                        metadata JSONB
                    )
                """)
                self.db_session.execute(create_table_sql)
                
                # Create indexes
                self.db_session.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_doc_category 
                    ON generic_knowledge(doc_category)
                """))
                
                # For small datasets, skip ivfflat index (use sequential scan)
                # ivfflat requires significant memory and may not improve performance
                # for datasets with < 100 rows. Uncomment below for larger datasets:
                # self.db_session.execute(text("""
                #     CREATE INDEX IF NOT EXISTS idx_generic_embedding_cosine 
                #     ON generic_knowledge 
                #     USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10)
                # """))
                print("✓ Skipping ivfflat index for small dataset (using sequential scan)")
                
                self.db_session.commit()
                print("✓ generic_knowledge table ready")
        
        except Exception as e:
            print(f"⚠️  Table initialization warning: {e}")
            try:
                self.db_session.rollback()
            except:
                pass
    
    def add_chunks(self, chunks: List[GenericChunk]) -> int:
        """
        Add generic knowledge chunks to vector store.
        
        Args:
            chunks: List of GenericChunk objects
            
        Returns:
            Number of chunks added
        """
        if not chunks:
            print("⚠️  No chunks to add")
            return 0
        
        added_count = 0
        
        for chunk in chunks:
            try:
                # Generate embedding using OpenAI
                embeddings = self.embedding_model.encode([chunk.content], convert_to_numpy=False)
                embedding = embeddings[0] if embeddings else []
                
                # Generate unique ID
                chunk_id = f"{chunk.doc_category}_{chunk.chunk_index}"
                
                # Sanitize metadata (convert Decimal to float)
                sanitized_metadata = self._sanitize_metadata(chunk.metadata)
                
                # Convert metadata to JSON string for proper JSONB insertion
                metadata_json = json.dumps(sanitized_metadata)
                
                insert_sql = text("""
                    INSERT INTO generic_knowledge 
                    (id, doc_category, chunk_index, content, embedding, metadata)
                    VALUES 
                    (:id, :doc_category, :chunk_index, :content, 
                     CAST(:embedding AS vector), CAST(:metadata AS jsonb))
                    ON CONFLICT (id) DO UPDATE SET
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata
                """)
                
                # Convert embedding to list format
                embedding_list = self._convert_embedding_to_list(embedding)
                
                self.db_session.execute(insert_sql, {
                    'id': chunk_id,
                    'doc_category': chunk.doc_category,
                    'chunk_index': chunk.chunk_index,
                    'content': chunk.content,
                    'embedding': embedding_list,
                    'metadata': metadata_json
                })
                
                added_count += 1
            
            except Exception as e:
                print(f"❌ Failed to add chunk {chunk.doc_category}_{chunk.chunk_index}: {e}")
                try:
                    self.db_session.rollback()
                except:
                    pass
        
        # Commit all changes
        try:
            self.db_session.commit()
            print(f"✓ Added {added_count} generic knowledge chunks")
        except Exception as e:
            print(f"❌ Commit failed: {e}")
            self.db_session.rollback()
            return 0
        
        return added_count
    
    def search(
        self,
        query: str,
        doc_categories: Optional[List[str]] = None,
        n_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search generic knowledge base.
        
        Args:
            query: Search query
            doc_categories: Optional filter by document categories
            n_results: Number of results to return
            
        Returns:
            List of matching chunks with similarity scores
        """
        # Generate query embedding using OpenAI
        query_embeddings = self.embedding_model.encode([query], convert_to_numpy=False)
        query_embedding = query_embeddings[0] if query_embeddings else []
        
        # Build SQL query
        category_filter = ""
        if doc_categories:
            category_filter = "AND doc_category = ANY(:categories)"
        
        sql = text(f"""
            SELECT 
                id,
                doc_category,
                chunk_index,
                content,
                metadata,
                1 - (embedding <=> CAST(:query_embedding AS vector)) as similarity
            FROM generic_knowledge
            WHERE 1=1
            {category_filter}
            ORDER BY embedding <=> CAST(:query_embedding AS vector)
            LIMIT :n_results
        """)
        
        # Convert query embedding to list format
        query_embedding_list = self._convert_embedding_to_list(query_embedding)
        
        params = {
            'query_embedding': query_embedding_list,
            'n_results': n_results
        }
        
        if doc_categories:
            params['categories'] = doc_categories
        
        try:
            with self._handle_errors():
                result = self.db_session.execute(sql, params)
                rows = result.fetchall()
                
                return self._format_search_results(rows)
        
        except Exception as e:
            print(f"❌ Search failed: {e}")
            return []
    
    def _format_search_results(self, rows: List) -> List[Dict[str, Any]]:
        """
        Format search result rows into dictionaries.
        
        Args:
            rows: List of database result rows
            
        Returns:
            List of formatted result dictionaries
        """
        results = []
        for row in rows:
            results.append({
                'id': row[0],
                'doc_category': row[1],
                'chunk_index': row[2],
                'content': row[3],
                'metadata': row[4],
                'similarity': float(row[5])
            })
        return results
    
    def delete_by_category(self, doc_category: str) -> int:
        """
        Delete all chunks for a document category.
        
        Args:
            doc_category: Category to delete
            
        Returns:
            Number of chunks deleted
        """
        try:
            with self._handle_errors():
                result = self.db_session.execute(
                    text("DELETE FROM generic_knowledge WHERE doc_category = :category"),
                    {'category': doc_category}
                )
                self.db_session.commit()
                count = result.rowcount
                print(f"✓ Deleted {count} chunks for category '{doc_category}'")
                return count
        except Exception as e:
            print(f"❌ Delete failed: {e}")
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about generic knowledge base.
        
        Returns:
            Dictionary with total_chunks and categories count
        """
        try:
            with self._handle_errors():
                # Total count
                total_result = self.db_session.execute(
                    text("SELECT COUNT(*) FROM generic_knowledge")
                )
                total = total_result.scalar()
                
                # Count by category
                category_result = self.db_session.execute(
                    text("""
                        SELECT doc_category, COUNT(*) 
                        FROM generic_knowledge 
                        GROUP BY doc_category
                    """)
                )
                categories = {row[0]: row[1] for row in category_result.fetchall()}
                
                return {
                    'total_chunks': total,
                    'categories': categories
                }
        except Exception as e:
            print(f"❌ Stats retrieval failed: {e}")
            return {'total_chunks': 0, 'categories': {}}
    
    def _sanitize_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert Decimal objects to float for JSON serialization.
        
        Recursively converts all Decimal objects in metadata to float,
        ensuring the metadata can be serialized to JSON.
        
        Args:
            metadata: Metadata dictionary that may contain Decimal objects
            
        Returns:
            Sanitized metadata dictionary with all Decimals converted to floats
            
        Raises:
            ValueError: If metadata cannot be serialized to JSON
        """
        def convert(obj: Any) -> Any:
            """Recursively convert Decimal to float."""
            if isinstance(obj, Decimal):
                return float(obj)
            elif isinstance(obj, dict):
                return {k: convert(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert(item) for item in obj]
            return obj
        
        sanitized = convert(metadata)
        # Validate JSON serialization
        json.dumps(sanitized)
        return sanitized
    
    def close(self):
        """Close database session if owned"""
        if self._owns_session and self.db_session:
            try:
                self.db_session.close()
                print("✓ Generic knowledge store session closed")
            except:
                pass

