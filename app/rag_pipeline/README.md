# RAG Pipeline for Property Listing Enquiries

Complete implementation of the AI enquiry system for automatically answering buyer questions about properties.

## Problem Statement Implementation

✅ **AI reads enquiry and searches listing information** - Implemented via retrieval system  
✅ **Uses property description, specifications, pricing, bid guidelines** - All chunk types supported  
✅ **Gives factual answers from listing data only** - Enforced via strict prompts  
✅ **Offers general bid advice (no financial recommendations)** - Specialized prompt for bidding  
✅ **Escalates to human if data insufficient** - Automatic escalation detection  
✅ **Includes disclaimer in every response** - Mandatory disclaimer enforcement  
✅ **Logs question, response, and data sources** - Complete logging system  

## Pipeline Components

### 1. **schemas.py** - Data Models
- `BuyerEnquiry`: Input schema for buyer questions
- `AIResponse`: Output schema with answer, escalation flags, data sources
- `DataSource`: Tracks which chunks were used
- `EnquiryLog`: Complete logging schema
- `PropertyListing`: Property data structure

### 2. **llms.py** - LLM Configuration
- OpenAI client setup
- Model configuration (gpt-4o-mini by default)
- Environment variable support (OPENAI_API_KEY)
- Configurable temperature and max tokens

### 3. **preprocess.py** - Query Preprocessing
- Extracts listing IDs from queries (UUID patterns)
- Normalizes queries (removes extra whitespace, cleans up)
- Detects enquiry type (price, specs, location, bidding, general)
- Prepares queries for retrieval

### 4. **augmentation.py** - Context Retrieval
- `QueryAugmenter`: Retrieves relevant listing chunks
- Formats retrieved context for LLM
- Tracks data sources used
- Checks data sufficiency (determines if escalation needed)

### 5. **prompts.py** - Prompt Templates
- **System Prompt**: Strict rules for factual, safe responses
- **User Prompt**: Formats query + context
- **Bid Advice Prompt**: Specialized for bidding questions (no financial advice)
- Includes disclaimer templates

### 6. **generation.py** - Response Generation
- `ResponseGenerator`: Main orchestration class
- Integrates retrieval → augmentation → LLM generation
- Enforces disclaimer inclusion
- Detects escalation needs
- Creates complete log entries

### 7. **postprocess.py** - Response Formatting
- Formats responses for API output
- Validates responses (disclaimer check, non-empty)
- Prepares final output structure

## Usage Example

```python
from app.rag_pipeline.preprocess import preprocess_enquiry
from app.rag_pipeline.generation import ResponseGenerator
from app.rag_pipeline.schemas import BuyerEnquiry
from app.rag_pipeline.postprocess import format_response_for_api

# 1. Create enquiry
enquiry = BuyerEnquiry(
    question="What is the price of properties with 3 bedrooms?",
    listing_id=None,  # Optional: specific listing
    user_id="user123",
    session_id="session456"
)

# 2. Preprocess
enquiry_data = preprocess_enquiry(enquiry)

# 3. Generate response
generator = ResponseGenerator()
result = generator.generate_response_from_enquiry(enquiry_data)

# 4. Format for API
api_response = format_response_for_api(
    ai_response=result["ai_response"],
    log_entry=result["log_entry"]
)

print(api_response["answer"])
print(f"Needs Human: {api_response['needs_human']}")
print(f"Data Sources: {len(api_response['data_sources'])}")
```

## Environment Setup

Create a `.env` file:
```bash
OPENAI_API_KEY=your_api_key_here
```

Or set environment variable:
```bash
export OPENAI_API_KEY=your_api_key_here
```

## Response Structure

```json
{
  "answer": "The property has 3 bedrooms and is priced at $500,000...",
  "needs_human": false,
  "escalation_reason": null,
  "data_sources": [
    {
      "chunk_type": "pricing",
      "listing_id": "xxx-xxx-xxx",
      "content_preview": "Asking Price: $500,000...",
      "similarity_score": 0.85
    }
  ],
  "disclaimer": "Based on available listing details..."
}
```

## Escalation Logic

The system escalates to human agents when:
1. **No data found**: No relevant listing information retrieved
2. **Missing critical info**: Query asks for price/specs/location but not in data
3. **LLM indicates gaps**: Response contains multiple "not available" phrases
4. **LLM error**: Generation fails

## Bid Advice Rules

For bidding/offer questions:
- ✅ Explains sale method (auction, private sale)
- ✅ Provides general process guidance
- ✅ Recommends independent advice
- ✅ Suggests reviewing comparables and budget
- ❌ NEVER suggests specific bid amounts
- ❌ NEVER says what vendor will accept

## Logging

Every enquiry is logged with:
- Question text
- AI response
- Data sources used (chunk types, listing IDs, similarity scores)
- Escalation flags and reasons
- Timestamp, user ID, session ID
- Model and prompt versions

## Integration with Vector Store

The pipeline uses the `PropertyRetriever` from `retrieval.py`:
- Automatic query intent detection
- Hybrid retrieval (all chunks for matched listings)
- Intelligent reranking
- Enhanced previews

## Next Steps

1. **Create API endpoint** in `main.py` to expose this functionality
2. **Set up logging storage** (database table for `EnquiryLog`)
3. **Implement escalation workflow** (notify agents when `needs_human=True`)
4. **Add monitoring** (track response quality, escalation rates)

