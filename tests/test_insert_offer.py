"""
Test script to insert a test offer and verify database write access.
"""
import app.config  # Load config first

from sqlalchemy import text
from app.db.session import SessionLocal
import uuid
from datetime import datetime, timezone

listing_id_1 = "950b945a-5604-49a0-9cf9-3d3c16cf9c1a"
listing_id_2 = "0d824a89-147e-436e-817e-804a4bc488d1"

db = SessionLocal()
try:
    print("="*60)
    print("🔧 INSERTING TEST OFFERS")
    print("="*60)
    
    # Insert test offers for listing 1
    print(f"\n📝 Inserting 4 test offers for listing {listing_id_1}...")
    for i in range(4):
        offer_id = str(uuid.uuid4())
        result = db.execute(text("""
            INSERT INTO offers (
                id, 
                listing_id, 
                offer_price, 
                deposit_amount,
                signature_status,
                status,
                created_at,
                updated_at
            ) VALUES (
                :id,
                :listing_id,
                :offer_price,
                :deposit_amount,
                :signature_status,
                'pending',
                :created_at,
                :updated_at
            )
        """), {
            "id": offer_id,
            "listing_id": listing_id_1,
            "offer_price": 500000 + (i * 10000),
            "deposit_amount": 50000,
            "signature_status": "offeree_signed" if i < 2 else "offeror_signed",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        })
        result.close()
        print(f"   ✅ Inserted offer {i+1}: {offer_id}")
    
    # Insert test offers for listing 2
    print(f"\n📝 Inserting 2 test offers for listing {listing_id_2}...")
    for i in range(2):
        offer_id = str(uuid.uuid4())
        result = db.execute(text("""
            INSERT INTO offers (
                id, 
                listing_id, 
                offer_price, 
                deposit_amount,
                signature_status,
                status,
                created_at,
                updated_at
            ) VALUES (
                :id,
                :listing_id,
                :offer_price,
                :deposit_amount,
                :signature_status,
                'pending',
                :created_at,
                :updated_at
            )
        """), {
            "id": offer_id,
            "listing_id": listing_id_2,
            "offer_price": 600000 + (i * 10000),
            "deposit_amount": 60000,
            "signature_status": "offeree_signed",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        })
        result.close()
        print(f"   ✅ Inserted offer {i+1}: {offer_id}")
    
    # COMMIT the transaction
    db.commit()
    print(f"\n✅ COMMITTED all test offers to database")
    
    # Verify the insertions
    print(f"\n{'='*60}")
    print("🔍 VERIFYING INSERTIONS")
    print("="*60)
    
    for listing_id in [listing_id_1, listing_id_2]:
        result = db.execute(text("""
            SELECT COUNT(*) FROM offers WHERE listing_id = :listing_id
        """), {"listing_id": listing_id})
        count = result.scalar()
        result.close()
        print(f"   Listing {listing_id}: {count} offers")
    
    print(f"\n{'='*60}")
    print("✅ TEST COMPLETE - Now try the activity API endpoint!")
    print("="*60)
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    db.rollback()
    raise
finally:
    db.close()
