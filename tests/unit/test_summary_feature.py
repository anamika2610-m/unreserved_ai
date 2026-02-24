#!/usr/bin/env python3
"""
Test script for the summary feature.

Tests:
1. Get listings with conversations
2. Generate summary for a listing
3. Retrieve summary from database
4. Test cron job functionality
"""
import sys
import os

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../")
)
sys.path.insert(0, PROJECT_ROOT)


from app.db.session import SessionLocal
from app.db.postgres.repositories.conversation_repository import ConversationRepository
from app.db.postgres.repositories.listing_summary_repository import ListingSummaryRepository
from app.db.postgres.repositories.listing_repository import ListingRepository
from app.services.chat_summary_service import ChatSummaryService
from app.services.summary_cron_service import SummaryCronService
from sqlalchemy import select, distinct
from app.db.models.conversation import Conversation
from uuid import UUID


def test_listings_with_conversations():
    """Test: Get listings that have conversations."""
    print("\n" + "="*80)
    print("TEST 1: Get listings with conversations")
    print("="*80)
    
    db = SessionLocal()
    try:
        query = select(distinct(Conversation.listing_id)).where(
            Conversation.is_active.is_(True),
            Conversation.listing_id.isnot(None)
        )
        result = db.execute(query)
        listing_ids = [row[0] for row in result.fetchall() if row[0]]
        
        print(f"✅ Found {len(listing_ids)} listings with conversations")
        if listing_ids:
            print(f"   Sample listing IDs:")
            for lid in listing_ids[:5]:
                print(f"   - {lid}")
        else:
            print("   ⚠️  No listings with conversations found")
            return None
        
        return listing_ids[0] if listing_ids else None
    finally:
        db.close()


def test_get_user_messages(listing_id: UUID):
    """Test: Get user messages for a listing."""
    print("\n" + "="*80)
    print(f"TEST 2: Get user messages for listing {listing_id}")
    print("="*80)
    
    db = SessionLocal()
    try:
        conversation_repo = ConversationRepository(db)
        user_messages = conversation_repo.get_listing_user_messages(
            listing_id=listing_id,
            limit_per_conversation=50
        )
        
        print(f"✅ Found {len(user_messages)} user messages")
        if user_messages:
            print(f"   Sample messages:")
            for msg in user_messages[:3]:
                content = msg.get('content', '')[:100]
                print(f"   - {content}...")
        else:
            print("   ⚠️  No user messages found")
        
        return user_messages
    finally:
        db.close()


def test_analyze_conversations(user_messages):
    """Test: Analyze conversations."""
    print("\n" + "="*80)
    print("TEST 3: Analyze conversations")
    print("="*80)
    
    summary_service = ChatSummaryService()
    analysis = summary_service.analyze_conversations(user_messages)
    
    print(f"✅ Analysis completed:")
    print(f"   Total queries: {analysis['total_queries']}")
    print(f"   Unique users estimate: {analysis['unique_users']}")
    print(f"   Query categories: {analysis['query_categories']}")
    print(f"   Frequent questions: {len(analysis['frequent_questions'])}")
    
    return analysis


def test_generate_summary(listing_id: UUID, analysis):
    """Test: Generate summary for a listing."""
    print("\n" + "="*80)
    print(f"TEST 4: Generate summary for listing {listing_id}")
    print("="*80)
    
    db = SessionLocal()
    try:
        summary_service = ChatSummaryService()
        listing_repo = ListingRepository(db)
        
        # Get property title
        property_title = None
        try:
            listing = listing_repo.get_by_id(listing_id)
            if listing:
                property_title = getattr(listing, 'slug', None) or str(listing_id)
        except:
            pass
        
        summary = summary_service.generate_summary(
            listing_id=str(listing_id),
            analysis=analysis,
            property_title=property_title,
        )
        
        print(f"✅ Summary generated ({len(summary)} characters)")
        print(f"\nSummary preview:")
        print("-" * 80)
        print(summary[:500] + "..." if len(summary) > 500 else summary)
        print("-" * 80)
        
        return summary
    finally:
        db.close()


def test_save_summary(listing_id: UUID, summary: str):
    """Test: Save summary to database."""
    print("\n" + "="*80)
    print(f"TEST 5: Save summary to database for listing {listing_id}")
    print("="*80)
    
    db = SessionLocal()
    try:
        summary_repo = ListingSummaryRepository(db)
        
        saved_summary = summary_repo.create_or_update(
            listing_id=listing_id,
            summary=summary,
            analysis=None,
        )
        
        print(f"✅ Summary saved to database")
        print(f"   Summary ID: {saved_summary.id}")
        print(f"   Listing ID: {saved_summary.listing_id}")
        print(f"   Last summarized at: {saved_summary.last_summarised_at}")
        print(f"   Created at: {saved_summary.created_at}")
        
        return saved_summary
    finally:
        db.close()


def test_retrieve_summary(listing_id: UUID):
    """Test: Retrieve summary from database."""
    print("\n" + "="*80)
    print(f"TEST 6: Retrieve summary from database for listing {listing_id}")
    print("="*80)
    
    db = SessionLocal()
    try:
        summary_repo = ListingSummaryRepository(db)
        summary = summary_repo.get_by_listing_id(listing_id)
        
        if summary:
            print(f"✅ Summary retrieved from database")
            print(f"   Summary ID: {summary.id}")
            print(f"   Last summarized at: {summary.last_summarised_at}")
            print(f"   Summary length: {len(summary.summary) if summary.summary else 0} characters")
            if summary.summary:
                print(f"\nSummary preview:")
                print("-" * 80)
                print(summary.summary[:500] + "..." if len(summary.summary) > 500 else summary.summary)
                print("-" * 80)
        else:
            print("   ⚠️  No summary found in database")
        
        return summary
    finally:
        db.close()


def test_cron_service():
    """Test: Test cron service functionality."""
    print("\n" + "="*80)
    print("TEST 7: Test cron service (dry run with max_listings=1)")
    print("="*80)
    
    cron_service = SummaryCronService()
    results = cron_service.run_nightly_summary_job(
        days_required=0,  # Set to 0 for testing (will generate for all)
        max_listings=1  # Only process 1 listing for testing
    )
    
    print(f"✅ Cron job completed:")
    print(f"   Listings processed: {results['listings_processed']}")
    print(f"   Listings succeeded: {results['listings_succeeded']}")
    print(f"   Listings failed: {results['listings_failed']}")
    print(f"   Listings skipped: {results['listings_skipped']}")
    
    if results['results']:
        print(f"\n   Results:")
        for result in results['results']:
            print(f"   - Listing {result['listing_id']}: {result['status']}")
    
    return results


def main():
    """Run all tests."""
    print("="*80)
    print("SUMMARY FEATURE TEST SUITE")
    print("="*80)
    
    # Test 1: Get listings with conversations
    listing_id = test_listings_with_conversations()
    if not listing_id:
        print("\n❌ Cannot proceed - no listings with conversations found")
        return
    
    # Test 2: Get user messages
    user_messages = test_get_user_messages(listing_id)
    if not user_messages:
        print("\n❌ Cannot proceed - no user messages found")
        return
    
    # Test 3: Analyze conversations
    analysis = test_analyze_conversations(user_messages)
    
    # Test 4: Generate summary
    summary = test_generate_summary(listing_id, analysis)
    
    # Test 5: Save summary
    saved_summary = test_save_summary(listing_id, summary)
    
    # Test 6: Retrieve summary
    retrieved_summary = test_retrieve_summary(listing_id)
    
    # Test 7: Test cron service
    cron_results = test_cron_service()
    
    print("\n" + "="*80)
    print("✅ ALL TESTS COMPLETED")
    print("="*80)
    print("\nTo test via API:")
    print(f"  GET  /api/v1/admin/listings/{listing_id}/summary")
    print(f"  POST /api/v1/admin/summaries/generate?days_required=0&max_listings=1")


if __name__ == "__main__":
    main()
