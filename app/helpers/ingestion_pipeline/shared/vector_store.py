"""
Vector store module for storing and retrieving property listing embeddings.
Uses ChromaDB for persistent vector storage.
"""
import os

# Disable tokenizer parallelism warning
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Support offline mode for HuggingFace models (set HF_HUB_OFFLINE=1 to work offline)
# This is useful when you have models cached but no internet connection

from typing import List, Dict, Any, Optional
from pathlib import Path
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from app.ingestion_pipeline.chunker import Chunk


class PropertyVectorStore:
    """
    Manages vector embeddings for property listings using ChromaDB.
    """
    
    def __init__(
        self,
        collection_name: str = "property_listings",
        persist_directory: str = "./chroma_db",
        embedding_model: str = "all-MiniLM-L6-v2"
    ):
        """
        Initialize the vector store.
        
        Args:
            collection_name: Name of the ChromaDB collection
            persist_directory: Directory to persist ChromaDB data
            embedding_model: Name of the sentence transformer model
        """
        self.collection_name = collection_name
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        
        # Initialize embedding model
        print(f"Loading embedding model: {embedding_model}")
        
        # Set offline mode if requested
        if os.environ.get("HF_HUB_OFFLINE", "0") == "1":
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            print("Running in offline mode...")
        
        try:
            self.embedding_model = SentenceTransformer(embedding_model)
            print(f"✓ Model loaded successfully")
        except Exception as e:
            error_str = str(e).lower()
            # Check if it's a network/connection error
            if any(keyword in error_str for keyword in ['connection', 'network', 'resolve', 'offline', 'internet']):
                raise RuntimeError(
                    f"Cannot load embedding model '{embedding_model}' - network error. "
                    "The model needs to be downloaded but there's no internet connection. "
                    "Please connect to the internet to download the model (it will be cached for future offline use)."
                )
            else:
                raise RuntimeError(
                    f"Failed to load embedding model '{embedding_model}': {str(e)}"
                )
        
        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=Settings(anonymized_telemetry=False)
        )
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
    
    def add_chunks(self, chunks: List[Chunk]) -> None:
        """
        Add chunks to the vector store.
        
        Args:
            chunks: List of Chunk objects to add
        """
        if not chunks:
            print("No chunks to add")
            return
        
        print(f"Adding {len(chunks)} chunks to vector store...")
        
        # Prepare data for ChromaDB
        documents = []
        metadatas = []
        ids = []
        
        for i, chunk in enumerate(chunks):
            # Create unique ID
            chunk_id = f"{chunk.listing_id}_{chunk.chunk_type}_{chunk.chunk_index}"
            
            documents.append(chunk.content)
            
            # Prepare metadata (ChromaDB requires string values)
            metadata = {
                'listing_id': str(chunk.listing_id),
                'property_id': str(chunk.metadata.get('property_id', '')),
                'chunk_type': chunk.chunk_type,
                'chunk_index': str(chunk.chunk_index),
            }
            
            # Add additional metadata fields (convert to strings)
            for key, value in chunk.metadata.items():
                if key not in metadata:
                    if value is None:
                        metadata[key] = ''
                    elif isinstance(value, (int, float)):
                        metadata[key] = str(value)
                    elif isinstance(value, bool):
                        metadata[key] = str(value)
                    elif isinstance(value, list):
                        metadata[key] = ', '.join(str(v) for v in value)
                    else:
                        metadata[key] = str(value)
            
            metadatas.append(metadata)
            ids.append(chunk_id)
        
        # Generate embeddings
        print("Generating embeddings...")
        embeddings = self.embedding_model.encode(
            documents,
            show_progress_bar=True,
            convert_to_numpy=True
        ).tolist()
        
        # Add to ChromaDB
        print("Storing in ChromaDB...")
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
        
        print(f"Successfully added {len(chunks)} chunks to vector store")
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search the vector store for similar chunks.
        
        Args:
            query: Search query text
            n_results: Number of results to return
            filter_metadata: Optional metadata filters (e.g., {'chunk_type': 'pricing'})
            
        Returns:
            List of search results with content, metadata, and distance
        """
        # Generate query embedding
        query_embedding = self.embedding_model.encode(
            query,
            convert_to_numpy=True
        ).tolist()
        
        # Prepare where clause for filtering
        where = None
        if filter_metadata:
            # Chroma requires a single operator at the root.
            # If multiple filters are provided, wrap them in $and.
            items = [
                {key: (str(value) if not isinstance(value, str) else value)}
                for key, value in filter_metadata.items()
            ]
            if len(items) == 1:
                where = items[0]
            else:
                where = {"$and": items}
        
        # Query ChromaDB
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where if where else None
        )
        
        # Format results
        formatted_results = []
        if results['ids'] and len(results['ids'][0]) > 0:
            for i in range(len(results['ids'][0])):
                formatted_results.append({
                    'id': results['ids'][0][i],
                    'content': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'distance': results['distances'][0][i] if 'distances' in results else None
                })
        
        return formatted_results
    
    def get_by_listing_id(self, listing_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all chunks for a specific listing.
        
        Args:
            listing_id: The listing ID to retrieve
            
        Returns:
            List of chunks for the listing
        """
        results = self.collection.get(
            where={"listing_id": str(listing_id)}
        )
        
        formatted_results = []
        if results['ids']:
            for i in range(len(results['ids'])):
                formatted_results.append({
                    'id': results['ids'][i],
                    'content': results['documents'][i],
                    'metadata': results['metadatas'][i]
                })
        
        return formatted_results
    
    def get_property_location(self, listing_id: str) -> Optional[Dict[str, Any]]:
        """
        Get property location (latitude, longitude) for a specific listing.
        
        Args:
            listing_id: The listing ID to get location for
            
        Returns:
            Dictionary with latitude and longitude, or None if not found
        """
        try:
            # Get location chunk for this listing
            results = self.collection.get(
                where={
                    "$and": [
                        {"listing_id": str(listing_id)},
                        {"chunk_type": "location"}
                    ]
                },
                limit=1
            )
            
            if results['ids'] and results['metadatas']:
                metadata = results['metadatas'][0]
                latitude = metadata.get('latitude')
                longitude = metadata.get('longitude')
                
                if latitude is not None and longitude is not None:
                    # Convert to float if they're strings
                    try:
                        lat = float(latitude)
                        lon = float(longitude)
                        return {
                            'latitude': lat,
                            'longitude': lon,
                            'address': metadata.get('address', '') or metadata.get('displayAddress', '')
                        }
                    except (ValueError, TypeError):
                        print(f"Invalid lat/lon values: {latitude}, {longitude}")
                        return None
            
            return None
        except Exception as e:
            print(f"Error getting property location: {e}")
            return None
    
    def update_chunks(self, chunks: List[Chunk]) -> None:
        """
        Update or add chunks to the vector store.
        If chunk IDs already exist, they will be deleted and re-added with new data.
        
        Args:
            chunks: List of Chunk objects to update/add
        """
        if not chunks:
            print("No chunks to update")
            return
        
        print(f"Updating {len(chunks)} chunks in vector store...")
        
        # First, delete existing chunks with the same IDs
        chunk_ids = [f"{chunk.listing_id}_{chunk.chunk_type}_{chunk.chunk_index}" for chunk in chunks]
        
        # Check which IDs exist
        try:
            existing = self.collection.get(ids=chunk_ids)
            existing_ids = existing['ids'] if existing['ids'] else []
            if existing_ids:
                print(f"Deleting {len(existing_ids)} existing chunks...")
                self.collection.delete(ids=existing_ids)
        except Exception as e:
            print(f"Note: No existing chunks to delete ({e})")
        
        # Now add the new chunks
        self.add_chunks(chunks)
    
    def delete_listing(self, listing_id: str) -> None:
        """
        Delete all chunks associated with a listing.
        
        Args:
            listing_id: The listing ID to delete
        """
        results = self.collection.get(where={"listing_id": str(listing_id)})
        
        if results['ids']:
            print(f"Deleting {len(results['ids'])} chunks for listing {listing_id}")
            self.collection.delete(ids=results['ids'])
        else:
            print(f"No chunks found for listing {listing_id}")
    
    def update_listing(self, listing_data: Dict[str, Any]) -> None:
        """
        Update a single listing in the vector store.
        Deletes old chunks and adds new ones.
        
        Args:
            listing_data: Formatted listing data dictionary
        """
        from app.ingestion_pipeline.loader import format_listing_for_chunking
        from app.ingestion_pipeline.chunker import PropertyListingChunker
        
        # Get listing ID
        listing_id = listing_data.get('id') or listing_data.get('data', {}).get('id')
        if not listing_id:
            print("Error: No listing ID found")
            return
        
        print(f"Updating listing: {listing_id}")
        
        # Delete existing chunks for this listing
        self.delete_listing(listing_id)
        
        # Format and chunk the listing
        formatted = format_listing_for_chunking(listing_data)
        chunker = PropertyListingChunker()
        chunks = chunker.chunk_listing(formatted)
        
        # Add new chunks
        self.add_chunks(chunks)
        print(f"Successfully updated listing {listing_id}")
    
    def delete_collection(self) -> None:
        """Delete the entire collection (use with caution)."""
        self.client.delete_collection(name=self.collection_name)
        print(f"Deleted collection: {self.collection_name}")
    
    def get_collection_info(self) -> Dict[str, Any]:
        """Get information about the collection."""
        count = self.collection.count()
        return {
            'collection_name': self.collection_name,
            'chunk_count': count,
            'persist_directory': str(self.persist_directory)
        }
    
    def clear_collection(self) -> None:
        """Clear all data from the collection."""
        self.delete_collection()
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        print(f"Cleared collection: {self.collection_name}")


def initialize_vector_store(
    data_file: str = "app/knowledge_base/sample_data.json",
    collection_name: str = "property_listings",
    persist_directory: str = "./chroma_db",
    clear_existing: bool = False
) -> PropertyVectorStore:
    """
    Initialize and populate the vector store with property listings.
    
    Args:
        data_file: Path to the JSON file containing property listings
        collection_name: Name of the ChromaDB collection
        persist_directory: Directory to persist ChromaDB data
        clear_existing: Whether to clear existing data before loading
        
    Returns:
        Initialized PropertyVectorStore instance
    """
    from app.ingestion_pipeline.loader import load_property_listings, format_listing_for_chunking
    from app.ingestion_pipeline.chunker import PropertyListingChunker
    
    # Initialize vector store
    vector_store = PropertyVectorStore(
        collection_name=collection_name,
        persist_directory=persist_directory
    )
    
    # Clear existing data if requested
    if clear_existing:
        print("Clearing existing vector store...")
        vector_store.clear_collection()
    
    # Check if collection already has data
    info = vector_store.get_collection_info()
    if info['chunk_count'] > 0 and not clear_existing:
        print(f"Vector store already contains {info['chunk_count']} chunks. Skipping load.")
        return vector_store
    
    # Load and process listings
    print(f"Loading listings from {data_file}...")
    listings = load_property_listings(data_file)
    print(f"Loaded {len(listings)} listings")
    
    # Format listings
    formatted_listings = [format_listing_for_chunking(listing) for listing in listings]
    
    # Chunk listings
    print("Chunking listings...")
    chunker = PropertyListingChunker()
    chunks = chunker.chunk_all_listings(formatted_listings)
    print(f"Created {len(chunks)} chunks from {len(listings)} listings")
    
    # Add chunks to vector store
    vector_store.add_chunks(chunks)
    
    return vector_store


def sync_vector_store(
    data_file: str = "app/knowledge_base/sample_data.json",
    collection_name: str = "property_listings",
    persist_directory: str = "./chroma_db"
) -> PropertyVectorStore:
    """
    Sync vector store with current data file.
    Updates existing listings and adds new ones.
    
    Args:
        data_file: Path to the JSON file containing property listings
        collection_name: Name of the ChromaDB collection
        persist_directory: Directory to persist ChromaDB data
        
    Returns:
        PropertyVectorStore instance
    """
    from app.ingestion_pipeline.loader import load_property_listings, format_listing_for_chunking
    from app.ingestion_pipeline.chunker import PropertyListingChunker
    
    print("=" * 60)
    print("Syncing Vector Store with Data File")
    print("=" * 60)
    
    # Initialize vector store
    vector_store = PropertyVectorStore(
        collection_name=collection_name,
        persist_directory=persist_directory
    )
    
    # Load listings from file
    print(f"Loading listings from {data_file}...")
    listings = load_property_listings(data_file)
    print(f"Loaded {len(listings)} listings from file")
    
    # Get existing listing IDs from vector store
    try:
        all_data = vector_store.collection.get()
        existing_listing_ids = set(all_data['metadatas'][i]['listing_id'] 
                                   for i in range(len(all_data['ids'])) 
                                   if 'listing_id' in all_data['metadatas'][i])
        print(f"Found {len(existing_listing_ids)} unique listings in vector store")
    except Exception as e:
        print(f"No existing data in vector store: {e}")
        existing_listing_ids = set()
    
    # Process each listing
    updated_count = 0
    new_count = 0
    
    for listing in listings:
        # Get listing ID
        listing_id = listing.get('id') or listing.get('data', {}).get('id')
        
        if not listing_id:
            print("Warning: Listing without ID found, skipping")
            continue
        
        if str(listing_id) in existing_listing_ids:
            print(f"Updating listing: {listing_id}")
            vector_store.update_listing(listing)
            updated_count += 1
        else:
            print(f"Adding new listing: {listing_id}")
            formatted = format_listing_for_chunking(listing)
            chunker = PropertyListingChunker()
            chunks = chunker.chunk_listing(formatted)
            vector_store.add_chunks(chunks)
            new_count += 1
    
    print("\n" + "=" * 60)
    print("Sync Complete!")
    print("=" * 60)
    print(f"Updated: {updated_count} listings")
    print(f"Added: {new_count} new listings")
    print(f"Total in vector store: {vector_store.collection.count()} chunks")
    
    return vector_store

