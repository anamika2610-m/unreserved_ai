"""
Example script demonstrating how to use the retrieval system.
"""
import os
import sys
from pathlib import Path

# Disable ChromaDB telemetry to avoid errors
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.rag_pipeline.retrieval import PropertyRetriever


def main():
    """Demonstrate retrieval functionality."""
    print("=" * 60)
    print("Property Listing Retrieval Example")
    print("=" * 60)
    
    # Get project root directory (parent of scripts directory)
    project_root = Path(__file__).parent.parent
    chroma_db_path = project_root / "chroma_db"
    
    # Initialize retriever with the same path used during initialization
    retriever = PropertyRetriever(
        collection_name="property_listings",
        persist_directory=str(chroma_db_path)
    )
    
    # Check collection info
    info = retriever.vector_store.get_collection_info()
    print(f"Collection: {info['collection_name']}")
    print(f"Total Chunks: {info['chunk_count']}")
    print(f"Storage Location: {info['persist_directory']}\n")
    
    if info['chunk_count'] == 0:
        print("WARNING: Vector store is empty! Please run initialize_vector_store.py first.\n")
        return
    
    # Example queries
    queries = [
        "What is the price of properties with 3 bedrooms?",
        "Show me auction properties in Sydney",
        "What are the specifications for properties with swimming pools?",
        "How much should I bid on auction properties?",
    ]
    
    for query in queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print('='*60)
        
        # Retrieve relevant chunks
        results = retriever.retrieve(query, n_results=3)
        
        # Display results with improved previews
        if results:
            for i, result in enumerate(results, 1):
                print(f"\n[Result {i}]")
                print(f"Chunk Type: {result['metadata'].get('chunk_type', 'unknown')}")
                print(f"Listing ID: {result['metadata'].get('listing_id', 'unknown')}")
                
                # Show better preview - ensure highlights/amenities are visible
                content = result.get('content', '')
                chunk_type = result['metadata'].get('chunk_type', '')
                
                # For specifications, try to show highlights
                if chunk_type == 'specifications' and 'Special Features:' in content:
                    highlight_idx = content.find('Special Features:')
                    preview = content[:min(len(content), highlight_idx + 250)]
                    if len(content) > len(preview):
                        preview += "..."
                    print(f"Content: {preview}")
                else:
                    # Show first 300 chars for other types
                    preview = content[:300] + "..." if len(content) > 300 else content
                    print(f"Content: {preview}")
                
                if result.get('distance'):
                    similarity = 1.0 - result['distance']
                    print(f"Similarity Score: {similarity:.4f}")
        else:
            print("No results found.")
    
    # Example: Retrieve specific listing information
    print(f"\n{'='*60}")
    print("Retrieving specific listing information")
    print('='*60)
    
    # Get a listing ID from the sample data (you can modify this)
    listing_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    listing_chunks = retriever.retrieve_for_listing(listing_id)
    
    print(f"\nFound {len(listing_chunks)} chunks for listing {listing_id}")
    for chunk in listing_chunks[:2]:  # Show first 2
        print(f"\nChunk Type: {chunk['metadata'].get('chunk_type')}")
        print(f"Content: {chunk['content'][:300]}...")


if __name__ == "__main__":
    main()

