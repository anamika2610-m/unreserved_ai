"""
Script to initialize and populate the vector store with property listings.
Run this script to load sample_data.json into the vector store.
"""
import os
import sys
from pathlib import Path

# Disable ChromaDB telemetry to avoid errors
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ingestion_pipeline.vector_store import initialize_vector_store


def main():
    """Initialize the vector store with property listings."""
    print("=" * 60)
    print("Initializing Property Listings Vector Store")
    print("=" * 60)
    
    # Get project root directory (parent of scripts directory)
    project_root = Path(__file__).parent.parent
    data_file = project_root / "app" / "knowledge_base" / "sample_data.json"
    
    # Check if file exists
    if not data_file.exists():
        print(f"Error: File not found: {data_file}")
        print("Please ensure the sample_data.json file exists.")
        return
    
    # Convert to string for the function call
    data_file_str = str(data_file)
    
    # Initialize vector store
    try:
        vector_store = initialize_vector_store(
            data_file=data_file_str,
            collection_name="property_listings",
            persist_directory=str(project_root / "chroma_db"),
            clear_existing=False  # Set to True to rebuild from scratch
        )
        
        # Print collection info
        info = vector_store.get_collection_info()
        print("\n" + "=" * 60)
        print("Vector Store Initialized Successfully!")
        print("=" * 60)
        print(f"Collection: {info['collection_name']}")
        print(f"Total Chunks: {info['chunk_count']}")
        print(f"Storage Location: {info['persist_directory']}")
        print("\nYou can now use the vector store for retrieval!")
        
    except Exception as e:
        print(f"\nError initializing vector store: {e}")
        import traceback
        traceback.print_exc()
        return


if __name__ == "__main__":
    main()

