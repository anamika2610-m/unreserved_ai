"""
Quick script to check if property_document chunks exist for a listing.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.helpers.ingestion_pipeline.property.pgvector_store import PgVectorStore

def check_property_documents(listing_id: str):
    """Check if property_document chunks exist for a listing."""
    print(f"Checking property documents for listing: {listing_id}\n")
    
    with PgVectorStore() as store:
        # Get all chunks for this listing
        all_chunks = store.get_by_listing_id(listing_id)
        
        # Filter property_document chunks
        # chunk_type is a direct field, not in metadata
        pdf_chunks = [
            chunk for chunk in all_chunks
            if chunk.get('chunk_type') == 'property_document'
        ]
        
        # Count by chunk type
        chunk_types = {}
        for chunk in all_chunks:
            chunk_type = chunk.get('chunk_type', 'unknown')
            chunk_types[chunk_type] = chunk_types.get(chunk_type, 0) + 1
        
        print(f"Total chunks for listing: {len(all_chunks)}")
        print(f"Property document chunks: {len(pdf_chunks)}")
        print(f"\nChunk types breakdown:")
        for chunk_type, count in sorted(chunk_types.items()):
            print(f"  - {chunk_type}: {count}")
        
        if pdf_chunks:
            print(f"\n✅ Property documents found! Sample chunks:")
            for i, chunk in enumerate(pdf_chunks[:3], 1):
                metadata = chunk.get('metadata', {})
                content = chunk.get('content', '')
                print(f"\n  {i}. File: {metadata.get('file_name', 'N/A')}")
                print(f"     Content preview: {content[:100]}...")
        else:
            print(f"\n⚠️  No property_document chunks found for this listing.")
            print(f"   Run: python app/helpers/ingestion_pipeline/property/sync_property_pdfs.py --listing-id {listing_id}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_property_documents.py <listing_id>")
        sys.exit(1)
    
    listing_id = sys.argv[1]
    check_property_documents(listing_id)

