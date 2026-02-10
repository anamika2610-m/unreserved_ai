"""
Query-based service for calculating listing activity metrics from existing tables.
No separate table needed - calculates on-the-fly from conversations and chat_messages.
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_, distinct, case
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models.conversation import Conversation, ChatMessage, ConversationRole


class ListingActivityRepository:
    """
    Query-based repository that calculates activity metrics from existing tables.
    No separate table needed - queries conversations and chat_messages on-the-fly.
    """
    
    def __init__(self, db_session: Session):
        self.db_session = db_session
    
    def get_activity_dict(self, listing_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Calculate activity metrics from existing tables.
        
        Args:
            listing_id: Listing UUID
            
        Returns:
            Dictionary of metrics
        """
        # Get listing created_at date from listings table
        from sqlalchemy import text
        
        listing_query = text("""
            SELECT created_at, published_at 
            FROM listings 
            WHERE id = :listing_id
        """)
        
        result = self.db_session.execute(
            listing_query, {"listing_id": str(listing_id)}
        )
        listing_result = result.fetchone()
        result.close()
        # ✅ MUST commit read-only queries to prevent "idle in transaction"
        # Even though FastAPI's get_db() manages session lifecycle, we need to
        # explicitly commit/rollback to close the transaction immediately
        self.db_session.commit()
        
        if not listing_result:
            return None
        
        listing_created_at = listing_result.created_at or listing_result.published_at
        if not listing_created_at:
            return None
        
        # Calculate time windows
        # Ensure both datetimes are timezone-aware
        now = datetime.now(timezone.utc)
        
        # If listing_created_at is naive, make it timezone-aware
        if listing_created_at.tzinfo is None:
            listing_created_at = listing_created_at.replace(tzinfo=timezone.utc)
        
        # First-week window: from listing_created_at to +7 days
        first_week_start = listing_created_at
        first_week_cutoff = listing_created_at + timedelta(days=7)
        
        # Rolling 7-day window: from now-7d to now
        rolling_end = now
        rolling_start = now - timedelta(days=7)
        
        print(f"🔍 Activity metrics calculation for listing {listing_id}")
        print(f"   Listing created_at: {listing_created_at}")
        print(f"   First-week window: {first_week_start} to {first_week_cutoff}")
        print(f"   Rolling 7-day window: {rolling_start} to {rolling_end}")
        
        # Initialize all metrics to 0
        enquiries_7d = 0
        repeat_buyers_7d = 0
        property_type = "house"
        first_inspection_groups_7d = 0
        first_inspection_date = None
        multi_inspection_buyers_7d = 0
        contract_requests_7d = 0
        genuine_offers_7d = 0
        competing_offers_7d = 0
        bp_inspections_7d = 0
        
        # 1. Enquiries from listing_crm_enquiries and enquiries tables
        # Note: enquiries table links to listings via listing_crm_enquiry_id -> listing_crm_enquiries.listing_id
        try:
            enquiries_7d_query = text("""
                SELECT COUNT(*) 
                FROM (
                    SELECT id FROM listing_crm_enquiries
                    WHERE listing_id = :listing_id 
                    AND created_at BETWEEN :listing_start AND :week_cutoff
                    UNION ALL
                    SELECT e.id FROM enquiries e
                    INNER JOIN listing_crm_enquiries lce ON e.listing_crm_enquiry_id = lce.id
                    WHERE lce.listing_id = :listing_id 
                    AND e.created_at BETWEEN :listing_start AND :week_cutoff
                ) AS combined_enquiries
            """)
            
            result = self.db_session.execute(
                enquiries_7d_query,
                {
                    "listing_id": str(listing_id),
                    # Use rolling 7-day window for current activity metrics
                    "listing_start": rolling_start,
                    "week_cutoff": rolling_end,
                }
            )
            enquiries_7d = result.scalar() or 0
            result.close()
            print(f"   ✅ enquiries_7d: {enquiries_7d}")
            # Don't commit read-only queries - let FastAPI's get_db() handle session cleanup
        except Exception as e:
            print(f"⚠️  Error querying enquiries: {e}")
            import traceback
            print(traceback.format_exc())
            try:
                self.db_session.rollback()
            except:
                pass
        
        # Repeat buyers (buyers with >= 2 enquiries in first 7 days)
        # Note: Only enquiries table has user_id, listing_crm_enquiries doesn't have buyer identifier
        try:
            repeat_buyers_7d_query = text("""
                SELECT COUNT(*)
                FROM (
                    SELECT e.user_id
                    FROM enquiries e
                    INNER JOIN listing_crm_enquiries lce ON e.listing_crm_enquiry_id = lce.id
                    WHERE lce.listing_id = :listing_id 
                    AND e.created_at BETWEEN :listing_start AND :week_cutoff
                    AND e.user_id IS NOT NULL
                    GROUP BY e.user_id
                    HAVING COUNT(*) >= 2
                ) AS repeat_buyers
            """)
            
            result = self.db_session.execute(
                repeat_buyers_7d_query,
                {
                    "listing_id": str(listing_id),
                    "listing_start": rolling_start,
                    "week_cutoff": rolling_end,
                }
            )
            repeat_buyers_7d = result.scalar() or 0
            result.close()
            print(f"   ✅ repeat_buyers_7d: {repeat_buyers_7d}")
            # Don't commit read-only queries
        except Exception as e:
            print(f"⚠️  Error querying repeat buyers: {e}")
            import traceback
            print(traceback.format_exc())
            try:
                self.db_session.rollback()
            except:
                pass
        
        # 2. Get property type from properties table
        try:
            property_type_query = text("""
                SELECT pt.name 
                FROM listings l
                JOIN properties p ON l.property_id = p.id
                JOIN property_types pt ON p.property_type_id = pt.id
                WHERE l.id = :listing_id
            """)
            
            result = self.db_session.execute(
                property_type_query, {"listing_id": str(listing_id)}
            )
            property_type_result = result.fetchone()
            result.close()
            # Don't commit read-only queries
            
            if property_type_result and property_type_result[0]:
                property_type_name = property_type_result[0].lower()
                if "apartment" in property_type_name or "unit" in property_type_name:
                    property_type = "apartment"
                else:
                    property_type = "house"
        except Exception as e:
            print(f"⚠️  Error querying property type: {e}")
            try:
                self.db_session.rollback()
            except:
                pass
        
        # 3. First inspection groups (within rolling 7 days)
        # Note:
        # - registered_inspections links to listing_inspections via listing_inspection_id
        # - We use the registration timestamp (registered_inspections.created_at) for the rolling
        #   7-day window, not the scheduled inspection_start_time (which may be in the future).
        # - This matches the UX expectation: once an inspection is attended "now", it should be
        #   reflected in the current rolling metrics.
        # - We still keep the concept of "first" by using the earliest attended registration time
        #   in the rolling window, then counting groups at that time.
        try:
            # First, get the earliest attended registration time in the rolling window
            first_date_query = text("""
                SELECT MIN(ri.created_at) AS first_inspection_time
                FROM registered_inspections ri
                INNER JOIN listing_inspections li ON ri.listing_inspection_id = li.id
                WHERE li.listing_id = :listing_id
                  AND ri.attendance_status = 'attended'
                  AND ri.created_at BETWEEN :listing_start AND :week_cutoff
            """)
            
            result = self.db_session.execute(
                first_date_query,
                {
                    "listing_id": str(listing_id),
                    "listing_start": rolling_start,
                    "week_cutoff": rolling_end,
                }
            )
            first_date_result = result.scalar()
            result.close()
            
            if first_date_result:
                first_inspection_time = first_date_result
                # Now count groups (registrations) at that first attended inspection time
                groups_query = text("""
                    SELECT COUNT(DISTINCT ri.id) AS groups_count
                    FROM registered_inspections ri
                    INNER JOIN listing_inspections li ON ri.listing_inspection_id = li.id
                    WHERE li.listing_id = :listing_id
                      AND ri.attendance_status = 'attended'
                      AND ri.created_at = :first_inspection_time
                """)
                
                result = self.db_session.execute(
                    groups_query,
                    {
                        "listing_id": str(listing_id),
                        "first_inspection_time": first_inspection_time,
                    }
                )
                first_inspection_groups_7d = result.scalar() or 0
                result.close()
                print(f"   ✅ first_inspection_groups_7d: {first_inspection_groups_7d} (first attended registration time: {first_inspection_time})")
            else:
                print(f"   ℹ️  No first inspection found in 7-day window")
        except Exception as e:
            print(f"⚠️  Error querying inspections: {e}")
            import traceback
            print(traceback.format_exc())
            try:
                self.db_session.rollback()
            except:
                pass
        
        # 4. Multi-inspection buyers (buyers with >= 2 attended inspections in rolling 7 days)
        try:
            multi_inspection_buyers_7d_query = text("""
                SELECT COUNT(*) 
                FROM (
                    SELECT ri.user_id
                    FROM registered_inspections ri
                    INNER JOIN listing_inspections li ON ri.listing_inspection_id = li.id
                    WHERE li.listing_id = :listing_id
                      AND ri.attendance_status = 'attended'
                      AND ri.created_at BETWEEN :listing_start AND :week_cutoff
                      AND ri.user_id IS NOT NULL
                    GROUP BY ri.user_id
                    HAVING COUNT(DISTINCT ri.listing_inspection_id) >= 2
                ) AS multi_buyers
            """)
            
            result = self.db_session.execute(
                multi_inspection_buyers_7d_query,
                {
                    "listing_id": str(listing_id),
                    "listing_start": rolling_start,
                    "week_cutoff": rolling_end,
                }
            )
            multi_inspection_buyers_7d = result.scalar() or 0
            result.close()
            print(f"   ✅ multi_inspection_buyers_7d: {multi_inspection_buyers_7d}")
            # Don't commit read-only queries
        except Exception as e:
            print(f"⚠️  Error querying multi-inspection buyers: {e}")
            import traceback
            print(traceback.format_exc())
            try:
                self.db_session.rollback()
            except:
                pass
        
        # 5. Contract requests (offers with signature_status != "offeror_sign_pending" in first 7 days)
        try:
            # Debug: Check all offers for this listing first
            debug_offers_query = text("""
                SELECT id, signature_status, created_at, listing_id
                FROM offers
                WHERE listing_id = :listing_id
                ORDER BY created_at DESC
                LIMIT 10
            """)
            
            debug_result = self.db_session.execute(
                debug_offers_query,
                {"listing_id": str(listing_id)}
            )
            debug_offers = debug_result.fetchall()
            debug_result.close()
            
            if debug_offers:
                print(f"   🔍 Found {len(debug_offers)} total offers for this listing:")
                matching_count = 0
                for offer in debug_offers:
                    offer_date = offer[2]
                    is_in_range = listing_created_at <= offer_date <= first_week_cutoff
                    has_valid_status = offer[1] != 'offeror_sign_pending'
                    matches = is_in_range and has_valid_status
                    if matches:
                        matching_count += 1
                    
                    status_icon = "✅" if matches else "❌"
                    print(f"      {status_icon} Offer {offer[0]}: signature_status={offer[1]}, created_at={offer_date}")
                    if not is_in_range:
                        print(f"         ⚠️  Outside date range (window: {listing_created_at} to {first_week_cutoff})")
                    if not has_valid_status:
                        print(f"         ⚠️  Has excluded signature_status")
            else:
                print(f"   ℹ️  No offers found for this listing")
            
            # Now run the actual query
            contract_requests_7d_query = text("""
                SELECT COUNT(*)
                FROM offers
                WHERE listing_id = :listing_id
                AND signature_status != 'offeror_sign_pending'
                AND created_at BETWEEN :listing_start AND :week_cutoff
            """)
            
            result = self.db_session.execute(
                contract_requests_7d_query,
                {
                    "listing_id": str(listing_id),
                    "listing_start": rolling_start,
                    "week_cutoff": rolling_end,
                }
            )
            contract_requests_7d = result.scalar() or 0
            result.close()
            print(
                f"   ✅ contract_requests_7d: {contract_requests_7d} "
                f"(filtered by rolling 7-day window {rolling_start} to {rolling_end} "
                f"and signature_status != 'offeror_sign_pending')"
            )
            # Don't commit read-only queries
        except Exception as e:
            print(f"⚠️  Error querying contract requests: {e}")
            import traceback
            print(traceback.format_exc())
            try:
                self.db_session.rollback()
            except:
                pass
        
        # 6. Genuine offers (same as contract requests: signature_status != "offeror_sign_pending")
        genuine_offers_7d = contract_requests_7d
        
        # 7. Competing offers (distinct buyers with offers in first 7 days where offer count >= 8)
        # Note: Join through bid_id -> auction_bids.bidder_id to get the buyer
        try:
            competing_offers_7d_query = text("""
                SELECT COUNT(*)
                FROM (
                    SELECT COALESCE(ab.bidder_id, o.action_by) as buyer_id
                    FROM offers o
                    LEFT JOIN auction_bids ab ON o.bid_id = ab.id
                    WHERE o.listing_id = :listing_id
                    AND o.created_at BETWEEN :listing_start AND :week_cutoff
                    AND (ab.bidder_id IS NOT NULL OR o.action_by IS NOT NULL)
                    GROUP BY COALESCE(ab.bidder_id, o.action_by)
                    HAVING COUNT(*) >= 8
                ) AS competing_buyers
            """)
            
            result = self.db_session.execute(
                competing_offers_7d_query,
                {
                    "listing_id": str(listing_id),
                    "listing_start": rolling_start,
                    "week_cutoff": rolling_end,
                }
            )
            competing_offers_7d = result.scalar() or 0
            result.close()
            print(f"   ✅ competing_offers_7d: {competing_offers_7d}")
            # Don't commit read-only queries
        except Exception as e:
            print(f"⚠️  Error querying competing offers: {e}")
            import traceback
            print(traceback.format_exc())
            try:
                self.db_session.rollback()
            except:
                pass
        
        # 8. B&P inspections (document_requests with is_b_and_p_inspection_required = true)
        try:
            bp_inspections_7d_query = text("""
                SELECT COUNT(DISTINCT id)
                FROM document_requests
                WHERE listing_id = :listing_id
                AND is_b_and_p_inspection_required = true
                AND created_at BETWEEN :listing_start AND :week_cutoff
            """)
            
            result = self.db_session.execute(
                bp_inspections_7d_query,
                {
                    "listing_id": str(listing_id),
                    "listing_start": rolling_start,
                    "week_cutoff": rolling_end,
                }
            )
            bp_inspections_7d = result.scalar() or 0
            result.close()
            print(f"   ✅ bp_inspections_7d: {bp_inspections_7d}")
            # Don't commit read-only queries
        except Exception as e:
            print(f"⚠️  Error querying B&P inspections: {e}")
            import traceback
            print(traceback.format_exc())
            try:
                self.db_session.rollback()
            except:
                pass
        
        # ✅ CRITICAL: Commit to close the transaction and prevent "idle in transaction"
        # All queries above are read-only, but the transaction MUST be closed
        try:
            self.db_session.commit()
        except Exception as e:
            print(f"⚠️  Failed to commit read transaction: {e}")
            try:
                self.db_session.rollback()
            except:
                pass
        
        return {
            "listing_id": str(listing_id),
            "listing_created_at": listing_created_at,
            "property_type": property_type,
            "enquiries_7d": enquiries_7d,
            "repeat_buyers_7d": repeat_buyers_7d,
            "first_inspection_groups_7d": first_inspection_groups_7d,
            "first_inspection_date": first_inspection_date,
            "multi_inspection_buyers_7d": multi_inspection_buyers_7d,
            "contract_requests_7d": contract_requests_7d,
            "genuine_offers_7d": genuine_offers_7d,
            "competing_offers_7d": competing_offers_7d,
            "bp_inspections_7d": bp_inspections_7d,
        }
