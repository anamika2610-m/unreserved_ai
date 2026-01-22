"""
Fix chunk_type for property PDF chunks that were incorrectly labeled as "unknown".

This script updates existing chunks in the database:
- If chunk_type = "unknown" AND metadata.source = "property_document" 
  → Update chunk_type to "property_document"

Usage:
    python app/helpers/ingestion_pipeline/property/fix_chunk_types.py
    # OR from project root:
    python -m app.helpers.ingestion_pipeline.property.fix_chunk_types
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root.resolve()))

from app.db.session import SessionLocal
from app.helpers.ingestion_pipeline.property.pgvector_store import PropertyEmbedding
from sqlalchemy import text


def fix_chunk_types():
    """Fix chunk_type for property PDF chunks labeled as 'unknown'."""
    print("=" * 70)
    print("Fixing chunk_type for property PDF chunks")
    print("=" * 70)
    
    db = SessionLocal()
    try:
        # Find all chunks with chunk_type = 'unknown' that have source = 'property_document' in metadata
        print("\n🔍 Searching for chunks with chunk_type='unknown' and source='property_document'...")
        
        query = text("""
            SELECT id, listing_id, chunk_index, metadata
            FROM property_embeddings
            WHERE chunk_type = 'unknown'
            AND metadata->>'source' = 'property_document'
        """)
        
        result = db.execute(query)
        rows = result.fetchall()
        
        print(f"   Found {len(rows)} chunks to fix")
        
        if len(rows) == 0:
            print("\n✅ No chunks need fixing!")
            return
        
        # Update each chunk
        print(f"\n🔧 Updating {len(rows)} chunks...")
        updated_count = 0
        
        for row in rows:
            chunk_id = row[0]
            listing_id = row[1]
            chunk_index = row[2]
            
            update_query = text("""
                UPDATE property_embeddings
                SET chunk_type = 'property_document'
                WHERE id = :chunk_id
            """)
            
            db.execute(update_query, {"chunk_id": chunk_id})
            updated_count += 1
            
            if updated_count % 10 == 0:
                print(f"   Updated {updated_count}/{len(rows)} chunks...")
        
        db.commit()
        print(f"\n✅ Successfully updated {updated_count} chunks from 'unknown' to 'property_document'")
        
        # Verify the fix
        print("\n🔍 Verifying fix...")
        verify_query = text("""
            SELECT COUNT(*) 
            FROM property_embeddings
            WHERE chunk_type = 'unknown'
            AND metadata->>'source' = 'property_document'
        """)
        result = db.execute(verify_query)
        remaining = result.scalar()
        
        if remaining == 0:
            print("✅ All chunks fixed successfully!")
        else:
            print(f"⚠️  Warning: {remaining} chunks still have chunk_type='unknown'")
        
        # Show statistics
        stats_query = text("""
            SELECT chunk_type, COUNT(*) as count
            FROM property_embeddings
            GROUP BY chunk_type
            ORDER BY count DESC
        """)
        result = db.execute(stats_query)
        rows = result.fetchall()
        
        print("\n📊 Current chunk_type distribution:")
        for row in rows:
            print(f"   {row[0]}: {row[1]} chunks")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    fix_chunk_types()
