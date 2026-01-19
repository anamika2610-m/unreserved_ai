"""
OpenAI Embeddings Wrapper

Provides a unified interface for generating embeddings using OpenAI's API.
Designed to be compatible with SentenceTransformer-like interfaces for easy migration.

Usage:
    from app.helpers.ingestion_pipeline.shared.openai_embeddings import OpenAIEmbeddings
    
    embeddings = OpenAIEmbeddings()
    vectors = embeddings.encode(["text to embed"])
"""
import os
from typing import List, Optional, Union
from openai import OpenAI, APIError, RateLimitError

# Try to import numpy for optional numpy array support
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

# OpenAI embedding model configuration
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"  # 1536 dimensions
# Alternative: "text-embedding-3-large"  # 3072 dimensions (more expensive)

# Vector dimension for OpenAI text-embedding-3-small
VECTOR_DIMENSION = 1536

# Default batch size for API calls
DEFAULT_BATCH_SIZE = 100


class OpenAIEmbeddings:
    """
    Wrapper for OpenAI embeddings API.
    Provides a similar interface to SentenceTransformer for easy migration.
    """
    
    def __init__(self, api_key: Optional[str] = None, model: str = OPENAI_EMBEDDING_MODEL):
        """
        Initialize OpenAI embeddings client.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Embedding model name (default: text-embedding-3-small)
        """
        self.model = model
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        
        if not api_key:
            raise ValueError(
                "OpenAI API key is required. Set OPENAI_API_KEY environment variable "
                "or pass api_key parameter."
            )
        
        try:
            self.client = OpenAI(api_key=api_key)
        except Exception as e:
            raise ValueError(f"Failed to initialize OpenAI client: {e}") from e
    
    def encode(
        self,
        texts: List[str],
        show_progress_bar: bool = False,
        convert_to_numpy: bool = True,
        batch_size: int = DEFAULT_BATCH_SIZE
    ) -> Union[List[List[float]], List]:
        """
        Encode texts into embeddings.
        
        Args:
            texts: List of text strings to embed
            show_progress_bar: Ignored (kept for compatibility with SentenceTransformer)
            convert_to_numpy: If True, returns numpy arrays; if False, returns lists
            batch_size: Number of texts to process per API call (default: 100)
            
        Returns:
            List of embedding vectors. Each vector is a list of floats or numpy array
            depending on convert_to_numpy parameter.
            
        Raises:
            ValueError: If texts list is empty or invalid
            APIError: If OpenAI API call fails
            RateLimitError: If rate limit is exceeded
        """
        if not texts:
            return []
        
        if not isinstance(texts, list):
            raise ValueError(f"Expected list of strings, got {type(texts)}")
        
        all_embeddings = []
        
        # Process in batches to avoid rate limits
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(texts) + batch_size - 1) // batch_size
            
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=batch
                )
                
                # Extract embeddings from response
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
                
                if show_progress_bar:
                    print(f"  Processed batch {batch_num}/{total_batches} ({min(i + batch_size, len(texts))}/{len(texts)} texts)")
            
            except RateLimitError as e:
                error_msg = f"Rate limit exceeded for batch {batch_num}/{total_batches}"
                print(f"❌ {error_msg}: {e}")
                raise
            except APIError as e:
                error_msg = f"OpenAI API error for batch {batch_num}/{total_batches}"
                print(f"❌ {error_msg}: {e}")
                raise
            except Exception as e:
                error_msg = f"Unexpected error generating embeddings for batch {batch_num}/{total_batches}: {e}"
                print(f"❌ {error_msg}")
                raise RuntimeError(error_msg) from e
        
        # Convert to numpy if requested (for compatibility)
        if convert_to_numpy:
            if HAS_NUMPY:
                return [np.array(emb) for emb in all_embeddings]
            else:
                # If numpy not available, return as lists
                return all_embeddings
        
        return all_embeddings
    
    def encode_single(self, text: str) -> List[float]:
        """
        Encode a single text into an embedding.
        
        Args:
            text: Text string to embed
            
        Returns:
            Embedding vector as a list of floats
            
        Raises:
            ValueError: If text is empty or invalid
        """
        if not text or not isinstance(text, str):
            raise ValueError(f"Expected non-empty string, got {type(text)}")
        
        result = self.encode([text], convert_to_numpy=False)
        return result[0] if result else []

