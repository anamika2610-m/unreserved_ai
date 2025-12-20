"""
Script to sync vector store with updated property listings.
Run this whenever you modify sample_data.json to update embeddings.
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

from app.ingestion_pipeline.vector_store import sync_vector_store


def main():
    """Sync the vector store with current data file."""
    print("=" * 60)
    print("Property Listings Vector Store - Sync Tool")
    print("=" * 60)
    
    # Get project root directory (parent of scripts directory)
    project_root = Path(__file__).parent.parent
    data_file = project_root / "app" / "knowledge_base" / "sample_data.json"
    
    # Check if file exists
    if not data_file.exists():
        print(f"Error: File not found: {data_file}")
        print("Please ensure the sample_data.json file exists.")
        return
    
    # Sync vector store
    try:
        vector_store = sync_vector_store(
            data_file=str(data_file),
            collection_name="property_listings",
            persist_directory=str(project_root / "chroma_db")
        )
        
        print("\n✅ Sync successful! Your vector embeddings are now up to date.")
        print("You can now query with the latest data.")
        
    except Exception as e:
        print(f"\n❌ Error syncing vector store: {e}")
        import traceback
        traceback.print_exc()
        return


if __name__ == "__main__":
    main()

