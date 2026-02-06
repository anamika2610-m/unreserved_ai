"""
Service for dynamic AI tone adaptation based on listing activity metrics.

Adjusts AI response tone based on buyer interest signals:
- High enquiry volume → Confident tone
- High inspection attendance → Competitive framing
- Contract requests → Assertive and time-sensitive
- Multiple offers → Decisive, deadline-driven

When multiple conditions are satisfied at once, tones are applied in this priority order:
1. URGENT
2. TIME_SENSITIVE
3. COMPETITIVE
4. DECISIVE
5. CONFIDENT
"""
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from enum import Enum


class ToneLevel(str, Enum):
    """AI tone levels based on market activity."""
    NEUTRAL = "neutral"
    CONFIDENT = "confident"
    COMPETITIVE = "competitive"
    TIME_SENSITIVE = "time_sensitive"
    URGENT = "urgent"
    DECISIVE = "decisive"


class ToneAdaptationService:
    """
    Determines appropriate AI tone based on listing activity metrics.
    """
    
    def __init__(self):
        # Thresholds for tone adaptation (all based on first 7 days)
        self.ENQUIRIES_HIGH_THRESHOLD = 15  # 15-25+ enquiries in first 7 days
        self.ENQUIRIES_VERY_HIGH_THRESHOLD = 25
        
        self.HOUSE_INSPECTION_THRESHOLD = 20  # 20+ groups for houses
        self.APARTMENT_INSPECTION_THRESHOLD = 12  # 12-15+ groups for apartments
        
        self.CONTRACT_REQUESTS_THRESHOLD = 3  # 3+ contract requests in first 7 days
        
        self.GENUINE_OFFERS_THRESHOLD = 2  # 2+ genuine offers in first 7 days
        
        self.COMPETING_OFFERS_THRESHOLD = 1  # 1+ distinct buyers with >=8 offers in first 7 days
        
        self.BP_INSPECTIONS_THRESHOLD = 2  # 2+ independent B&P inspections in first 7 days
    
    def determine_tone(
        self,
        listing_activity: Dict[str, Any],
        current_context: Optional[str] = None
    ) -> Tuple[ToneLevel, str]:
        """
        Determine the appropriate AI tone based on listing activity metrics.
        
        Args:
            listing_activity: Dictionary containing listing activity metrics
            current_context: Optional context about the current query
            
        Returns:
            Tuple of (tone_level, tone_context_text)
        """
        if not listing_activity:
            return ToneLevel.NEUTRAL, ""
        
        # Extract metrics (all 7-day based)
        enquiries_7d = listing_activity.get("enquiries_7d", 0)
        repeat_buyers_7d = listing_activity.get("repeat_buyers_7d", 0)
        first_inspection_groups_7d = listing_activity.get("first_inspection_groups_7d", 0)
        multi_inspection_buyers_7d = listing_activity.get("multi_inspection_buyers_7d", 0)
        contract_requests_7d = listing_activity.get("contract_requests_7d", 0)
        genuine_offers_7d = listing_activity.get("genuine_offers_7d", 0)
        competing_offers_7d = listing_activity.get("competing_offers_7d", 0)
        bp_inspections_7d = listing_activity.get("bp_inspections_7d", 0)
        property_type = listing_activity.get("property_type", "house")
        
        # Prioritization: when multiple conditions are satisfied, apply the highest-priority tone.
        # Order: 1. URGENT → 2. TIME_SENSITIVE → 3. COMPETITIVE → 4. DECISIVE → 5. CONFIDENT
        inspection_threshold = (
            self.HOUSE_INSPECTION_THRESHOLD
            if property_type.lower() == "house"
            else self.APARTMENT_INSPECTION_THRESHOLD
        )

        # 1. URGENT: Multiple genuine offers OR 2+ B&P inspections
        if genuine_offers_7d >= self.GENUINE_OFFERS_THRESHOLD:
            return ToneLevel.URGENT, self._get_urgent_context(genuine_offers_7d)
        if bp_inspections_7d >= self.BP_INSPECTIONS_THRESHOLD:
            return ToneLevel.URGENT, self._get_urgent_bp_context(bp_inspections_7d)

        # 2. TIME_SENSITIVE: High contract requests
        if contract_requests_7d >= self.CONTRACT_REQUESTS_THRESHOLD:
            return ToneLevel.TIME_SENSITIVE, self._get_time_sensitive_context(contract_requests_7d)

        # 3. COMPETITIVE: High inspection attendance or multi-inspection buyers
        if (first_inspection_groups_7d >= inspection_threshold or
                multi_inspection_buyers_7d >= 3):
            return ToneLevel.COMPETITIVE, self._get_competitive_context(
                first_inspection_groups_7d,
                multi_inspection_buyers_7d,
            )

        # 4. DECISIVE: Competing offers
        if competing_offers_7d >= self.COMPETING_OFFERS_THRESHOLD:
            return ToneLevel.DECISIVE, self._get_decisive_context(competing_offers_7d)

        # 5. CONFIDENT: High enquiry volume or repeat buyers
        if (enquiries_7d >= self.ENQUIRIES_HIGH_THRESHOLD or
                repeat_buyers_7d >= 5):
            return ToneLevel.CONFIDENT, self._get_confident_context(
                enquiries_7d,
                repeat_buyers_7d,
            )

        # Default: NEUTRAL tone
        return ToneLevel.NEUTRAL, ""
    
    def _get_confident_context(self, enquiries: int, repeat_buyers: int) -> str:
        """Generate confident tone context."""
        context_parts = []
        
        if enquiries >= self.ENQUIRIES_VERY_HIGH_THRESHOLD:
            context_parts.append("This property has generated exceptional interest with significant enquiry volume.")
        elif enquiries >= self.ENQUIRIES_HIGH_THRESHOLD:
            context_parts.append("This property has attracted strong buyer interest.")
        
        if repeat_buyers >= 5:
            context_parts.append("Multiple buyers have made repeat enquiries showing serious interest.")
        
        return " ".join(context_parts)
    
    def _get_competitive_context(self, inspection_groups: int, multi_inspection: int) -> str:
        """Generate competitive tone context."""
        context_parts = []
        
        if inspection_groups > 0:
            context_parts.append(f"Good numbers through inspections with {inspection_groups}+ groups attending.")
        
        if multi_inspection >= 3:
            context_parts.append("Multiple buyers have returned for second viewings.")
            context_parts.append("Buyers are conducting detailed due diligence.")
        
        return " ".join(context_parts)
    
    def _get_time_sensitive_context(self, contract_requests: int) -> str:
        """Generate time-sensitive tone context."""
        context_parts = []
        
        if contract_requests >= 5:
            context_parts.append("Multiple buyers are actively reviewing contracts.")
        elif contract_requests >= 3:
            context_parts.append(f"{contract_requests} buyers have requested contracts.")
        
        context_parts.append("Legal review is underway with decisions expected shortly.")
        
        return " ".join(context_parts)
    
    def _get_urgent_context(self, genuine_offers: int) -> str:
        """Generate urgent tone context for genuine offers."""
        context_parts = []
        
        context_parts.append(f"Buyers are progressing to due diligence with {genuine_offers} formal offers.")
        context_parts.append("The campaign is entering its final stages.")
        
        return " ".join(context_parts)
    
    def _get_urgent_bp_context(self, bp_inspections: int) -> str:
        """Generate urgent tone context for B&P inspections."""
        context_parts = []
        
        context_parts.append(f"Buyers are progressing to due diligence with {bp_inspections} independent B&P inspections.")
        context_parts.append("The campaign is entering its final stages.")
        
        return " ".join(context_parts)
    
    def _get_decisive_context(self, competing_offers: int) -> str:
        """Generate decisive tone context."""
        context_parts = []
        
        context_parts.append(f"Multiple offers are under consideration in a competitive bidding environment.")
        context_parts.append("Buyers are being asked for their best and final positions.")
        
        return " ".join(context_parts)
    
    def format_tone_context_for_prompt(
        self,
        tone_level: ToneLevel,
        tone_context: str
    ) -> str:
        """
        Format tone context for injection into AI prompt.
        
        Args:
            tone_level: The determined tone level
            tone_context: The tone context text
            
        Returns:
            Formatted string for prompt injection
        """
        if tone_level == ToneLevel.NEUTRAL or not tone_context:
            return ""
        
        tone_instructions = {
            ToneLevel.CONFIDENT: "Present factual information about market activity in a clear, informative manner.",
            ToneLevel.COMPETITIVE: "Present factual information about market activity and buyer interest levels.",
            ToneLevel.TIME_SENSITIVE: "Present factual information about market activity and timing-related developments.",
            ToneLevel.URGENT: "Present factual information about market activity and current buyer activity levels.",
            ToneLevel.DECISIVE: "Present factual information about market activity and competitive dynamics.",
        }
        
        instruction = tone_instructions.get(tone_level, "")
        
        return f"""
=== MARKET ACTIVITY CONTEXT ===
{tone_context}

TONE INSTRUCTION: {instruction}

🚨 CRITICAL LEGAL COMPLIANCE RULES:
- NEVER provide recommendations, advice, or suggestions about whether to buy, bid, or make offers
- NEVER tell users what they "should" do, "must" do, or "need" to do
- NEVER create urgency or pressure users to take action
- ONLY present factual information about market activity when relevant to the user's question
- If asked "should I buy this home?" or similar questions seeking advice, respond: "I cannot provide personal advice or recommendations. For questions about purchasing decisions, please consult with qualified professionals such as a lawyer, financial advisor, or licensed real estate agent."
- State facts only - do not interpret facts as recommendations
- Do not fabricate details, but do reference genuine market activity when factually relevant

When responding to buyer enquiries ABOUT A SPECIFIC PROPERTY (not generic knowledge questions):
- FIRST answer the user's factual question directly and clearly (for example, floor size, bedrooms, features, location).
- THEN, if there is meaningful market activity context above, you MAY add ONE short factual sentence summarising current buyer interest or activity for this property (for example, "There are currently 4 formal offers on this property."), keeping it neutral and non-persuasive.
- Do NOT suggest any course of action or imply the user should act because of this activity.
"""
