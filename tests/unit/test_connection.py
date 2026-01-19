#!/usr/bin/env python3
"""
Quick test script to verify database connection after SSL fixes.
"""
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from app.db.session import engine, SessionLocal

def main():
    print("="*70)
    print("DATABASE CONNECTION TEST (with SSL fixes)")
    print("="*70)
    
    # Show connection string (hide password)
    db_url = os.getenv('DATABASE_URL', 'NOT SET')
    if 'postgresql://' in db_url and '@' in db_url:
        masked = db_url.split('@')[0].split(':')[:-1]
        host_part = db_url.split('@')[1]
        print(f"URL: postgresql://***:***@{host_part}")
    else:
        print(f"URL: {db_url[:30]}...")
    
    print()
    
    # Test 1: Basic connection
    print("Test 1: Basic connection...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text('SELECT 1 as test'))
            assert result.scalar() == 1
            print("  ✓ Basic connection successful")
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return 1
    
    # Test 2: PostgreSQL version
    print("\nTest 2: PostgreSQL version...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text('SELECT version()'))
            version = result.scalar()
            print(f"  ✓ PostgreSQL: {version[:60]}...")
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return 1
    
    # Test 3: Check pgvector extension
    print("\nTest 3: pgvector extension...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
            ))
            has_vector = result.scalar()
            if has_vector:
                print("  ✓ pgvector extension is enabled")
            else:
                print("  ⚠️  pgvector extension NOT found (run sync script)")
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return 1
    
    # Test 4: Check embeddings table
    print("\nTest 4: property_embeddings table...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT COUNT(*) FROM property_embeddings"
            ))
            count = result.scalar()
            print(f"  ✓ Table exists with {count} embeddings")
    except Exception as e:
        print(f"  ⚠️  Table not found or empty: {e}")
        print("  Run: python tests/unit/sync_pgvector.py")
    
    # Test 5: Session pooling
    print("\nTest 5: Connection pooling (3 sequential queries)...")
    try:
        for i in range(3):
            session = SessionLocal()
            result = session.execute(text('SELECT current_database()'))
            db_name = result.scalar()
            print(f"  Query {i+1}: ✓ Connected to '{db_name}'")
            session.close()
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return 1
    
    print("\n" + "="*70)
    print("✓ ALL TESTS PASSED - Database connection is working!")
    print("="*70)
    print("\nYou can now run:")
    print("  python tests/unit/chat_listing_cli.py")
    print("  python tests/unit/sync_pgvector.py")
    return 0

if __name__ == "__main__":
    exit(main())

