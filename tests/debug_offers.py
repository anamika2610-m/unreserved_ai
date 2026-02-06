"""
Debug script to check offers table directly.
"""
import app.config  # Load config first

from sqlalchemy import text
from app.db.session import SessionLocal

listing_ids = [
    "950b945a-5604-49a0-9cf9-3d3c16cf9c1a",  # Should have 4 offers/contracts
    "0d824a89-147e-436e-817e-804a4bc488d1"   # Should have 2 offers/contracts
]

db = SessionLocal()
try:
    # Check if offers table exists and what tables contain 'offer' or 'contract'
    result = db.execute(text("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND (table_name LIKE '%offer%' OR table_name LIKE '%contract%')
        ORDER BY table_name
    """))
    tables = result.fetchall()
    result.close()
    
    print("="*60)
    print("Tables with 'offer' or 'contract' in name:")
    print("="*60)
    for row in tables:
        print(f"  - {row[0]}")
    
    # Check offers for both specific listings
    for listing_id in listing_ids:
        print(f"\n{'='*60}")
        print(f"Checking offers for listing {listing_id}:")
        print("="*60)
        
        result = db.execute(text("""
            SELECT id, signature_status, created_at
            FROM offers
            WHERE listing_id = :listing_id
            ORDER BY created_at DESC
        """), {"listing_id": listing_id})
        offers = result.fetchall()
        result.close()
        
        if offers:
            print(f"✅ Found {len(offers)} offers:")
            for o in offers:
                print(f"  - {o[0]}: signature_status={o[1]}, created_at={o[2]}")
        else:
            print(f"  ❌ No offers found")
    
    # Check all offers (any listing) created today
    print(f"\n{'='*60}")
    print("All offers created today (any listing):")
    print("="*60)
    
    result = db.execute(text("""
        SELECT id, listing_id, signature_status, created_at
        FROM offers
        WHERE DATE(created_at) = CURRENT_DATE
        ORDER BY created_at DESC
        LIMIT 10
    """))
    today_offers = result.fetchall()
    result.close()
    
    if today_offers:
        print(f"Found {len(today_offers)} offers created today:")
        for o in today_offers:
            print(f"  - {o[0]}: listing_id={o[1]}, signature_status={o[2]}, created_at={o[3]}")
    else:
        print("  ℹ️  No offers created today")
    
    # Check schema of contract_documents
    print(f"\n{'='*60}")
    print("Schema of contract_documents:")
    print("="*60)
    
    result = db.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'contract_documents'
        ORDER BY ordinal_position
    """))
    columns = result.fetchall()
    result.close()
    
    for col in columns:
        print(f"  - {col[0]}: {col[1]}")
    
    # Check schema of offers
    print(f"\n{'='*60}")
    print("Schema of offers:")
    print("="*60)
    
    result = db.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'offers'
        ORDER BY ordinal_position
    """))
    columns = result.fetchall()
    result.close()
    
    for col in columns:
        print(f"  - {col[0]}: {col[1]}")
    
    # Check offers with date filtering for both listings
    for listing_id in listing_ids:
        print(f"\n{'='*60}")
        print(f"Detailed check for listing {listing_id}:")
        print("="*60)
        
        # Total offers ever
        result = db.execute(text("""
            SELECT COUNT(*) FROM offers WHERE listing_id = :listing_id
        """), {"listing_id": listing_id})
        total_count = result.scalar()
        result.close()
        
        print(f"  📊 Total offers ever: {total_count}")
        
        # Last 30 days
        result = db.execute(text("""
            SELECT id, signature_status, created_at
            FROM offers
            WHERE listing_id = :listing_id
            AND created_at >= CURRENT_DATE - INTERVAL '30 days'
            ORDER BY created_at DESC
        """), {"listing_id": listing_id})
        recent_offers = result.fetchall()
        result.close()
        
        if recent_offers:
            print(f"  📅 Offers in last 30 days: {len(recent_offers)}")
            for o in recent_offers:
                print(f"     - {o[0]}: signature_status={o[1]}, created_at={o[2]}")
        else:
            print(f"  📅 Offers in last 30 days: 0")
        
        # Last 7 days (rolling window)
        result = db.execute(text("""
            SELECT id, signature_status, created_at
            FROM offers
            WHERE listing_id = :listing_id
            AND created_at >= NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC
        """), {"listing_id": listing_id})
        rolling_7d_offers = result.fetchall()
        result.close()
        
        if rolling_7d_offers:
            print(f"  📈 Offers in last 7 days (rolling): {len(rolling_7d_offers)}")
            for o in rolling_7d_offers:
                print(f"     - {o[0]}: signature_status={o[1]}, created_at={o[2]}")
        else:
            print(f"  📈 Offers in last 7 days (rolling): 0")
        
        # Contract requests (signature_status != 'offeror_sign_pending')
        result = db.execute(text("""
            SELECT id, signature_status, created_at
            FROM offers
            WHERE listing_id = :listing_id
            AND signature_status != 'offeror_sign_pending'
            AND created_at >= NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC
        """), {"listing_id": listing_id})
        contract_offers = result.fetchall()
        result.close()
        
        if contract_offers:
            print(f"  📝 Contract requests (last 7d, status != 'offeror_sign_pending'): {len(contract_offers)}")
            for o in contract_offers:
                print(f"     - {o[0]}: signature_status={o[1]}, created_at={o[2]}")
        else:
            print(f"  📝 Contract requests (last 7d, status != 'offeror_sign_pending'): 0")
    
    # Check if there are ANY offers at all in the entire database
    print(f"\n{'='*60}")
    print("Checking entire offers table:")
    print("="*60)
    
    result = db.execute(text("""
        SELECT COUNT(*) FROM offers
    """))
    total_offers = result.scalar()
    result.close()
    
    print(f"  🌍 Total offers in entire database: {total_offers}")
    
    if total_offers > 0:
        # Show some sample offers
        result = db.execute(text("""
            SELECT id, listing_id, signature_status, created_at
            FROM offers
            ORDER BY created_at DESC
            LIMIT 5
        """))
        sample_offers = result.fetchall()
        result.close()
        
        print(f"\n  📋 Sample of most recent offers:")
        for o in sample_offers:
            print(f"     - {o[0]}: listing_id={o[1]}, status={o[2]}, created_at={o[3]}")
    
    # Check the database connection URL being used
    print(f"\n{'='*60}")
    print("Database connection info:")
    print("="*60)
    
    result = db.execute(text("""
        SELECT current_database(), current_user, inet_server_addr(), inet_server_port()
    """))
    db_info = result.fetchone()
    result.close()
    
    print(f"  🔌 Database: {db_info[0]}")
    print(f"  👤 User: {db_info[1]}")
    print(f"  🌐 Server: {db_info[2]}:{db_info[3]}")
    
    # Check enum values for signature_status and status
    print(f"\n{'='*60}")
    print("Enum values for offers table:")
    print("="*60)
    
    result = db.execute(text("""
        SELECT t.typname, e.enumlabel
        FROM pg_type t 
        JOIN pg_enum e ON t.oid = e.enumtypid  
        WHERE t.typname IN ('offer_signature_status', 'offer_status')
        ORDER BY t.typname, e.enumsortorder
    """))
    enums = result.fetchall()
    result.close()
    
    current_type = None
    for enum in enums:
        if enum[0] != current_type:
            current_type = enum[0]
            print(f"\n  📋 {enum[0]}:")
        print(f"     - {enum[1]}")
        
finally:
    db.close()
