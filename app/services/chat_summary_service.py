"""
Chat Summary Service for Property-Level Conversation Analysis

Generates high-level summaries of user queries and themes for a specific listing,
helping administrators identify buyer interest patterns without exposing
individual user conversations.
"""

from typing import List, Dict, Any, Optional
from collections import Counter
from datetime import datetime
import re

from app.services.rag_pipeline.llms import create_chat_completion, get_model_config
from app.services.rag_pipeline.preprocess import detect_enquiry_type


class ChatSummaryService:
    """
    Service for generating property-level chat summaries.
    """

    # Query type categories for analysis - focused on property features and desired features
    QUERY_CATEGORIES = {
        "property_features": [
            "bedroom", "bathroom", "garage", "parking", "ensuite", "balcony", "deck",
            "garden", "yard", "pool", "swimming pool", "spa", "gym", "study", "office",
            "storage", "basement", "attic", "fireplace", "heating", "cooling", "air conditioning",
            "floor", "level", "stories", "storeys", "size", "area", "square meter", "sqm",
            "land area", "floor area", "frontage", "year built", "age", "renovated", "renovation"
        ],
        "desired_features": [
            "want", "looking for", "need", "require", "prefer", "interested in", "would like",
            "must have", "should have", "expect", "desire", "wish", "hope", "ideal"
        ],
        "amenities": [
            "amenity", "facility", "nearby", "close to", "walking distance", "school", "hospital",
            "shopping", "restaurant", "cafe", "park", "beach", "transport", "public transport",
            "train", "bus", "station", "supermarket", "gym", "fitness"
        ],
        "location": [
            "location", "address", "suburb", "area", "neighborhood", "neighbourhood",
            "distance", "km", "kilometer", "walking", "drive", "commute"
        ],
        "pricing": [
            "price", "cost", "asking", "auction", "bid", "reserve", "payment", "afford",
            "budget", "value", "worth"
        ],
        "property_type": [
            "house", "apartment", "unit", "townhouse", "villa", "duplex", "terrace",
            "studio", "penthouse", "land", "commercial"
        ],
    }

    def __init__(self):
        """Initialize the chat summary service."""
        pass

    def analyze_conversations(
        self,
        user_messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Analyze user messages to identify themes, patterns, and frequently asked questions.
        
        Args:
            user_messages: List of user message dictionaries (from get_listing_user_messages)
            
        Returns:
            Dictionary containing:
            - total_queries: Total number of user queries
            - unique_users: Estimated number of unique users (based on conversation patterns)
            - query_categories: Distribution of queries by category
            - frequent_questions: Most common question patterns
            - enquiry_types: Distribution of enquiry types
            - time_distribution: Query distribution over time periods
        """
        if not user_messages:
            return {
                "total_queries": 0,
                "unique_users": 0,
                "query_categories": {},
                "frequent_questions": [],
                "enquiry_types": {},
                "time_distribution": {},
            }

        total_queries = len(user_messages)
        
        # Categorize queries
        category_counts = Counter()
        enquiry_type_counts = Counter()
        question_patterns = []
        
        for msg in user_messages:
            content = msg.get("content", "").lower()
            query_type = msg.get("query_type", "unknown")
            
            # Detect enquiry type
            enquiry_type = detect_enquiry_type(content)
            enquiry_type_counts[enquiry_type] += 1
            
            # Categorize by keywords - allow multiple categories per query
            for category, keywords in self.QUERY_CATEGORIES.items():
                if any(keyword in content for keyword in keywords):
                    category_counts[category] += 1
                    # Don't break - allow query to match multiple categories
            
            # Extract question patterns (normalized)
            normalized = self._normalize_question(content)
            if normalized:
                question_patterns.append(normalized)
        
        # Find frequent question patterns
        pattern_counts = Counter(question_patterns)
        frequent_questions = [
            {"pattern": pattern, "count": count}
            for pattern, count in pattern_counts.most_common(10)
        ]
        
        # Time distribution (by day of week and hour if timestamps available)
        time_distribution = self._analyze_time_distribution(user_messages)
        
        return {
            "total_queries": total_queries,
            "unique_users": self._estimate_unique_users(user_messages),
            "query_categories": dict(category_counts),
            "frequent_questions": frequent_questions,
            "enquiry_types": dict(enquiry_type_counts),
            "time_distribution": time_distribution,
        }

    def generate_summary(
        self,
        listing_id: str,
        analysis: Dict[str, Any],
        property_title: Optional[str] = None,
    ) -> str:
        """
        Generate a natural language summary using LLM based on conversation analysis.
        
        Args:
            listing_id: Listing ID
            analysis: Analysis results from analyze_conversations
            property_title: Optional property title for context
            
        Returns:
            Generated summary text
        """
        if analysis["total_queries"] == 0:
            return (
                f"No user queries have been recorded for this listing yet. "
                f"Summary will be generated once users start asking questions about the property."
            )

        # Build context for LLM
        context_parts = []
        
        if property_title:
            context_parts.append(f"Property: {property_title}")
        
        context_parts.append(f"Total Queries: {analysis['total_queries']}")
        context_parts.append(f"Estimated Unique Users: {analysis['unique_users']}")
        
        if analysis["query_categories"]:
            categories_text = ", ".join(
                f"{cat}: {count}" for cat, count in sorted(
                    analysis["query_categories"].items(),
                    key=lambda x: x[1],
                    reverse=True
                )
            )
            context_parts.append(f"Query Categories: {categories_text}")
        
        if analysis["frequent_questions"]:
            top_questions = "\n".join(
                f"- {item['pattern']} (asked {item['count']} times)"
                for item in analysis["frequent_questions"][:5]
            )
            context_parts.append(f"Most Common Questions:\n{top_questions}")
        
        if analysis["enquiry_types"]:
            enquiry_text = ", ".join(
                f"{etype}: {count}" for etype, count in sorted(
                    analysis["enquiry_types"].items(),
                    key=lambda x: x[1],
                    reverse=True
                )
            )
            context_parts.append(f"Enquiry Types: {enquiry_text}")
        
        context = "\n".join(context_parts)
        
        # Create LLM prompt
        system_prompt = """You are an assistant that generates high-level summaries of user queries 
for property listings. Your summaries should:
1. Focus on PROPERTY FEATURES that buyers are asking about (bedrooms, bathrooms, amenities, etc.)
2. Identify DESIRED FEATURES that buyers are looking for (what they want, need, prefer)
3. Highlight trends and patterns in buyer interest
4. Provide insights about what features buyers care most about
5. Be concise and actionable for property administrators
6. NEVER mention specific user IDs or individual conversations
7. Focus on aggregate patterns and trends, especially property features and desired features

Generate a professional, informative summary that helps administrators understand 
what property features buyers are interested in and what they're looking for."""

        user_prompt = f"""Based on the following conversation analysis for a property listing, 
generate a comprehensive summary that identifies buyer interest patterns and common themes.

{context}

Generate a summary that:
- Focuses on PROPERTY FEATURES buyers are asking about (bedrooms, bathrooms, amenities, size, etc.)
- Identifies DESIRED FEATURES buyers are looking for (what they want, need, prefer)
- Highlights trends in buyer interest patterns related to property features
- Provides insights about which features buyers care most about
- Suggests what property information might be missing or needs clarification
- Is written in a professional, administrative tone

Keep the summary to 3-4 paragraphs maximum. Focus on property features and desired features."""

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            
            response = create_chat_completion(
                messages=messages,
                temperature=0.5,  # Slightly higher for more natural summaries
                max_tokens=500,
            )
            
            summary = response.choices[0].message.content.strip()
            return summary
            
        except Exception as e:
            print(f"⚠️  Error generating LLM summary: {e}")
            # Fallback to template-based summary
            return self._generate_fallback_summary(analysis)

    def _normalize_question(self, question: str) -> Optional[str]:
        """
        Normalize a question to extract its pattern (removing specific values).
        
        Examples:
        - "What is the price?" -> "what is the price"
        - "How many bedrooms?" -> "how many bedrooms"
        - "What's the address?" -> "what is the address"
        """
        # Convert to lowercase
        normalized = question.lower().strip()
        
        # Remove question marks and extra whitespace
        normalized = re.sub(r'\?+', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Remove common fillers
        fillers = ["please", "can you", "could you", "tell me", "i want to know"]
        for filler in fillers:
            if normalized.startswith(filler):
                normalized = normalized[len(filler):].strip()
        
        # Skip very short or empty questions
        if len(normalized) < 5:
            return None
        
        return normalized

    def _estimate_unique_users(self, messages: List[Dict[str, Any]]) -> int:
        """
        Estimate number of unique users based on conversation patterns.
        This is a rough estimate since we don't have user_id in the aggregated data.
        
        For now, we'll use a heuristic: if there are many messages with similar
        timestamps, they might be from the same user session.
        """
        # Simple heuristic: assume each conversation represents one user
        # In a real implementation, you might want to track this differently
        # For now, we'll estimate based on message count and time distribution
        if not messages:
            return 0
        
        # Group messages by approximate time windows (same hour = likely same user)
        time_groups = {}
        for msg in messages:
            created_at = msg.get("created_at")
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    # Group by hour
                    hour_key = dt.strftime("%Y-%m-%d %H:00")
                    if hour_key not in time_groups:
                        time_groups[hour_key] = 0
                    time_groups[hour_key] += 1
                except:
                    pass
        
        # Estimate: each time group with >1 message might be one user
        # Multiple time groups suggest multiple users
        unique_estimate = max(len(time_groups), len(messages) // 5)
        return unique_estimate

    def _analyze_time_distribution(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze time distribution of queries.
        
        Returns:
            Dictionary with day_of_week and hour_of_day distributions
        """
        day_counts = Counter()
        hour_counts = Counter()
        
        for msg in messages:
            created_at = msg.get("created_at")
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    day_counts[dt.strftime("%A")] += 1
                    hour_counts[dt.hour] += 1
                except:
                    pass
        
        return {
            "by_day": dict(day_counts),
            "by_hour": dict(hour_counts),
        }

    def _generate_fallback_summary(self, analysis: Dict[str, Any]) -> str:
        """
        Generate a template-based summary if LLM generation fails.
        """
        total = analysis["total_queries"]
        categories = analysis.get("query_categories", {})
        
        summary_parts = [
            f"This property listing has received {total} user queries.",
        ]
        
        if categories:
            top_category = max(categories.items(), key=lambda x: x[1])
            summary_parts.append(
                f"The most common topic is {top_category[0]} with {top_category[1]} queries."
            )
        
        if analysis.get("frequent_questions"):
            top_q = analysis["frequent_questions"][0]
            summary_parts.append(
                f"The most frequently asked question pattern is: '{top_q['pattern']}' "
                f"(asked {top_q['count']} times)."
            )
        
        summary_parts.append(
            "This indicates active buyer interest. Consider ensuring all property "
            "information is up-to-date and easily accessible."
        )
        
        return " ".join(summary_parts)
