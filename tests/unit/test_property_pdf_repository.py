#!/usr/bin/env python3
"""
Test script to verify property PDF fetching via repository layer.

Usage:
    python tests/unit/test_property_pdf_repository.py
"""
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.db.session import SessionLocal
from app.db.postgres.repositories import ListingRepository


def test_fetch_property_documents():
    """
    Test fetching property documents from database via repository.
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    print("=" * 70)
    print("Testing Property Document Fetching via Repository Layer")
    print("=" * 70)
    
    db = SessionLocal()
    try:
        listing_repo = ListingRepository(db)
        
        # Fetch all active listings
        print("\n1️⃣ Fetching all active listings...")
        try:
            listings = listing_repo.fetch_listings(listing_status="active", limit=5)
            print(f"   ✓ Fetched {len(listings)} active listings")
        except Exception as e:
            print(f"   ✗ Failed to fetch listings: {e}")
            return 1
        
        if not listings:
            print("\n⚠️  No active listings found in database")
            return 0
        
        # Try to fetch property documents for each listing
        print("\n2️⃣ Checking for property documents...")
        total_docs = 0
        listings_with_docs = 0
        errors = []
        
        for listing in listings:
            listing_id = listing.get('id')
            title = listing.get('title', 'N/A')
            
            if not listing_id:
                print(f"\n   ⚠️  Skipping listing with no ID: {title}")
                continue
            
            try:
                # Fetch property documents via repository
                property_docs = listing_repo.fetch_property_documents(listing_id)
                
                if property_docs:
                    total_docs += len(property_docs)
                    listings_with_docs += 1
                    print(f"\n   📍 Listing: {listing_id}")
                    print(f"      Title: {title}")
                    print(f"      Documents: {len(property_docs)}")
                    
                    for i, doc in enumerate(property_docs, 1):
                        metadata = doc.get('mediaMetadata', {})
                        print(f"\n      Document {i}:")
                        print(f"         ID: {doc.get('id')}")
                        print(f"         Display Order: {doc.get('displayOrder')}")
                        print(f"         File Name: {metadata.get('fileName')}")
                        print(f"         File Type: {metadata.get('fileType')}")
                        file_url = metadata.get('fileUrl')
                        print(f"         File URL: {file_url[:50]}..." if file_url and len(file_url) > 50 else f"         File URL: {file_url or 'N/A'}")
                        alt_text = metadata.get('altText')
                        print(f"         Alt Text: {alt_text[:50]}..." if alt_text and len(alt_text) > 50 else f"         Alt Text: {alt_text or 'N/A'}")
            except Exception as e:
                error_msg = f"Failed to fetch documents for listing {listing_id}: {e}"
                errors.append(error_msg)
                print(f"\n   ✗ {error_msg}")
        
        # Summary
        print("\n" + "=" * 70)
        print("📊 Summary")
        print("=" * 70)
        print(f"\n Total listings checked: {len(listings)}")
        print(f" Listings with documents: {listings_with_docs}")
        print(f" Total documents found: {total_docs}")
        
        if errors:
            print(f"\n ⚠️  Errors encountered: {len(errors)}")
            for error in errors:
                print(f"   - {error}")
        
        if total_docs == 0:
            print("\n⚠️  No property documents found in database")
            print("\n   To add property documents:")
            print("   1. Insert records into property_media table with category IN ('floor_plan', 'other')")
            print("   2. Ensure is_public = true and file_type = 'pdf' in media_metadata")
            print("   3. Run: python app/helpers/ingestion_pipeline/property/sync_property_pdfs.py")
            return 0
        else:
            print("\n✅ Property documents found! Ready for PDF ingestion.")
            print("   Run: python app/helpers/ingestion_pipeline/property/sync_property_pdfs.py")
            return 0
    
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    finally:
        db.close()


if __name__ == "__main__":
    exit(test_fetch_property_documents())

