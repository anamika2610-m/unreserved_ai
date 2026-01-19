"""
Complete Pipeline Demonstration Script
=====================================

Listing-scoped RAG demo with Chroma-safe retrieval.

Run:
    python scripts/demo_pipeline_steps.py
"""

import os
import re
import sys
from pathlib import Path
from typing import Any
from pprint import pprint

# -------------------------------------------------------------------------
# ENV SETUP
# -------------------------------------------------------------------------

os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# -------------------------------------------------------------------------
# IMPORTS
# -------------------------------------------------------------------------

from app.ingestion_pipeline.loader import load_property_listings, format_listing_for_chunking
from app.ingestion_pipeline.chunker import PropertyListingChunker
from app.ingestion_pipeline.vector_store import PropertyVectorStore

from app.rag_pipeline.preprocess import preprocess_enquiry, detect_enquiry_type
from app.rag_pipeline.retrieval import PropertyRetriever
from app.rag_pipeline.augmentation import QueryAugmenter
from app.rag_pipeline.generation import ResponseGenerator
from app.rag_pipeline.postprocess import (
    format_response_for_api,
    validate_response,
    sanitize_response,
)
from app.rag_pipeline.schemas import BuyerEnquiry

# -------------------------------------------------------------------------
# UTILS
# -------------------------------------------------------------------------

def print_section(title: str):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def print_step(title: str, description: str):
    print("\n" + "─" * 80)
    print(title)
    print("─" * 80)
    print(f"Description: {description}")
    print("─" * 80 + "\n")


def print_output(title: str, data: Any):
    print(f"📤 OUTPUT: {title}")
    print("─" * 80)
    pprint(data, width=100)
    print()


def print_info(title: str, value: Any):
    print(f"ℹ️  {title}: {value}\n")


def assert_price_in_answer(answer: str, expected_numeric: str = "250000"):
    """
    Assert that the answer contains the expected price, ignoring commas/currency.
    """
    digits_only = re.sub(r"[^\d]", "", answer)
    assert expected_numeric in digits_only, "❌ Wrong price retrieved"

# -------------------------------------------------------------------------
# DATA INGESTION
# -------------------------------------------------------------------------

def demo_data_ingestion_pipeline() -> PropertyVectorStore:
    print_section("DATA INGESTION PIPELINE")

    data_file = project_root / "app" / "knowledge_base" / "sample_data.json"
    persist_dir = project_root / "chroma_db"
    clear_existing = True  # Always rebuild for deterministic demo

    raw_listings = load_property_listings(str(data_file))
    print_info("Listings Loaded", len(raw_listings))

    formatted = format_listing_for_chunking(raw_listings[0])
    print_output("Formatted Listing (sample)", formatted)

    chunker = PropertyListingChunker()
    vector_store = PropertyVectorStore(
        collection_name="property_listings",
        persist_directory=str(persist_dir),
        embedding_model="all-MiniLM-L6-v2",
    )

    if clear_existing:
        print_info("Clearing Existing Collection", "true")
        vector_store.clear_collection()

    info = vector_store.get_collection_info()
    all_formatted = [format_listing_for_chunking(l) for l in raw_listings]
    all_chunks = chunker.chunk_all_listings(all_formatted)
    vector_store.add_chunks(all_chunks)

    print_output("Vector Store Info", vector_store.get_collection_info())
    return vector_store

# -------------------------------------------------------------------------
# RAG PIPELINE (LISTING SCOPED)
# -------------------------------------------------------------------------

def demo_rag_pipeline(vector_store: PropertyVectorStore):
    print_section("RAG PIPELINE (LISTING-SCOPED)")

    LISTING_ID = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

    test_queries = [
        "What is the price of this property?",
        "How many bedrooms does this property have?",
        "What is the sale method?",
    ]

    retriever = PropertyRetriever(vector_store)
    augmenter = QueryAugmenter(retriever=retriever)
    generator = ResponseGenerator(augmenter=augmenter)

    for idx, question in enumerate(test_queries, 1):
        print("\n" + "=" * 80)
        print(f"TEST QUERY {idx}: {question}")
        print("=" * 80)

        # ---------------- PREPROCESS ----------------
        print_step("STEP 1: PREPROCESS", "Normalize enquiry")

        enquiry = BuyerEnquiry(
            question=question,
            listing_id=LISTING_ID,
            user_id="demo_user",
            session_id=f"demo_session_{idx}",
        )

        preprocessed = preprocess_enquiry(enquiry)
        print_output("Preprocessed Enquiry", preprocessed)

        enquiry_type = detect_enquiry_type(question)
        print_info("Detected Enquiry Type", enquiry_type)

        # ---------------- RETRIEVAL ----------------
        print_step("STEP 2: RETRIEVAL", "Retrieve chunks for the listing")

        chunks = retriever.retrieve(
            query=preprocessed["normalized_query"],
            n_results=5,
            listing_id=LISTING_ID,
        )

        print_info("Retrieved Chunks", len(chunks))

        # 🔒 HARD GUARANTEE
        assert all(
            c["metadata"]["listing_id"] == LISTING_ID for c in chunks
        ), "❌ Cross-listing contamination detected"

        for c in chunks:
            print("\nChunk:")
            print("Type:", c["metadata"].get("chunk_type"))
            print("Preview:", c["content"][:250])

        # ---------------- AUGMENTATION ----------------
        print_step("STEP 3: AUGMENTATION", "Build LLM context")

        context, sources = augmenter.augment_query(
            query=preprocessed["normalized_query"],
            listing_id=LISTING_ID,
            n_results=5,
        )

        print_info("Context Length", len(context))
        print_info("Data Sources", len(sources))

        # ---------------- GENERATION ----------------
        print_step("STEP 4: GENERATION", "Generate answer")

        result = generator.generate_response_from_enquiry(preprocessed)
        ai_response = result["ai_response"]

        print_output("LLM Answer", ai_response.answer)

        # ---------------- POSTPROCESS ----------------
        print_step("STEP 5: POSTPROCESS", "Validate & format response")

        is_valid, error = validate_response(ai_response)
        print_info("Response Valid", is_valid)

        sanitized = sanitize_response(ai_response)

        api_response = format_response_for_api(
            ai_response=sanitized,
            log_entry=result["log_entry"],
        )

        print_output("Final API Response", api_response)

        # ✅ Deterministic check for price
        if enquiry_type == "price":
            assert_price_in_answer(ai_response.answer, expected_numeric="250000")

# -------------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------------

def main():
    print_section("COMPLETE PIPELINE DEMO")

    vector_store = demo_data_ingestion_pipeline()
    demo_rag_pipeline(vector_store)

    print_section("DEMO COMPLETE")
    print("✅ All pipelines executed successfully")


if __name__ == "__main__":
    main()





# """
# Complete Pipeline Demonstration Script
# =====================================

# This script demonstrates each step of both the Data Ingestion Pipeline and RAG Pipeline,
# showing actual inputs and outputs at every stage.

# Run from project root:
#     python scripts/demo_pipeline_steps.py
# """
# import os
# import sys
# import json
# from pathlib import Path
# from typing import Dict, Any, List
# from pprint import pprint

# # Fix tokenizers parallelism warning
# os.environ["TOKENIZERS_PARALLELISM"] = "false"

# # Disable ChromaDB telemetry to avoid errors
# os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
# os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")

# # Add project root to path
# project_root = Path(__file__).parent.parent
# sys.path.insert(0, str(project_root))

# # Import all pipeline components
# from app.ingestion_pipeline.loader import load_property_listings, format_listing_for_chunking
# from app.ingestion_pipeline.chunker import PropertyListingChunker, Chunk
# from app.ingestion_pipeline.vector_store import PropertyVectorStore
# from app.rag_pipeline.preprocess import preprocess_enquiry, detect_enquiry_type
# from app.rag_pipeline.retrieval import PropertyRetriever
# from app.rag_pipeline.augmentation import QueryAugmenter
# from app.rag_pipeline.generation import ResponseGenerator
# from app.rag_pipeline.postprocess import format_response_for_api, validate_response, sanitize_response
# from app.rag_pipeline.schemas import BuyerEnquiry, AIResponse
# from app.rag_pipeline.evaluations import RAGEvaluator, TestCase, get_default_test_cases


# def print_section(title: str, char: str = "=", width: int = 80):
#     """Print a formatted section header."""
#     print("\n" + char * width)
#     print(f"  {title}")
#     print(char * width + "\n")


# def print_step(step_num: int, step_name: str, description: str):
#     """Print a step header."""
#     print(f"\n{'─' * 80}")
#     print(f"STEP {step_num}: {step_name}")
#     print(f"{'─' * 80}")
#     print(f"Description: {description}")
#     print(f"{'─' * 80}\n")


# def print_input(title: str, data: Any, max_length: int = 500):
#     """Print input data."""
#     print(f"📥 INPUT: {title}")
#     print("─" * 80)
#     if isinstance(data, str) and len(data) > max_length:
#         print(data[:max_length] + f"\n... (truncated, total length: {len(data)} chars)")
#     elif isinstance(data, (dict, list)):
#         pprint(data, width=100, depth=3)
#     else:
#         print(data)
#     print()


# def print_output(title: str, data: Any, max_length: int = 500):
#     """Print output data."""
#     print(f"📤 OUTPUT: {title}")
#     print("─" * 80)
#     if isinstance(data, str) and len(data) > max_length:
#         print(data[:max_length] + f"\n... (truncated, total length: {len(data)} chars)")
#     elif isinstance(data, (dict, list)):
#         pprint(data, width=100, depth=3)
#     else:
#         print(data)
#     print()


# def print_info(title: str, data: Any):
#     """Print informational data."""
#     print(f"ℹ️  {title}: {data}\n")


# def demo_data_ingestion_pipeline():
#     """Demonstrate the complete data ingestion pipeline."""
#     print_section("DATA INGESTION PIPELINE", "=", 80)
    
#     # Setup paths
#     data_file = project_root / "app" / "knowledge_base" / "sample_data.json"
#     persist_dir = project_root / "chroma_db"
    
#     # ========================================================================
#     # STEP 1: LOADER
#     # ========================================================================
#     print_step(1, "LOADER", "Load and parse raw JSON property listing data")
    
#     print_input("File Path", str(data_file))
    
#     if not data_file.exists():
#         print("❌ ERROR: sample_data.json not found!")
#         print(f"   Expected at: {data_file}")
#         return None
    
#     # Load listings
#     print("🔄 Processing: Loading property listings from JSON...")
#     raw_listings = load_property_listings(str(data_file))
    
#     print_output(f"Raw Listings (count: {len(raw_listings)})", 
#                  f"List of {len(raw_listings)} listing dictionaries")
#     print_info("First listing keys", list(raw_listings[0].keys()) if raw_listings else "No listings")
    
#     # Show first listing structure
#     if raw_listings:
#         print("\n📋 Sample Raw Listing Structure:")
#         print("─" * 80)
#         sample_keys = {
#             "id": raw_listings[0].get("id", "N/A"),
#             "title": raw_listings[0].get("title", "N/A")[:50] + "..." if len(str(raw_listings[0].get("title", ""))) > 50 else raw_listings[0].get("title", "N/A"),
#             "has_location": "location" in raw_listings[0],
#             "has_propertyAttributes": "propertyAttributes" in raw_listings[0],
#         }
#         pprint(sample_keys, width=100)
#         print()
    
#     # Format first listing
#     print("🔄 Processing: Formatting listing for chunking...")
#     formatted_listing = format_listing_for_chunking(raw_listings[0])
    
#     print_output("Formatted Listing", formatted_listing)
#     print_info("Formatted listing keys", list(formatted_listing.keys()))
    
#     # ========================================================================
#     # STEP 2: CHUNKER
#     # ========================================================================
#     print_step(2, "CHUNKER", "Split formatted listing into semantic chunks")
    
#     print_input("Formatted Listing", formatted_listing)
    
#     print("🔄 Processing: Creating semantic chunks...")
#     chunker = PropertyListingChunker()
#     chunks = chunker.chunk_listing(formatted_listing)
    
#     print_output(f"Chunks Created (count: {len(chunks)})", 
#                  f"List of {len(chunks)} Chunk objects")
    
#     # Show each chunk
#     for i, chunk in enumerate(chunks):
#         print(f"\n📦 CHUNK {i+1}: {chunk.chunk_type.upper()}")
#         print("─" * 80)
#         print(f"Chunk Type: {chunk.chunk_type}")
#         print(f"Chunk Index: {chunk.chunk_index}")
#         print(f"Listing ID: {chunk.listing_id}")
#         print(f"Content Length: {len(chunk.content)} characters")
#         print(f"\nContent Preview:")
#         print(chunk.content[:300] + "..." if len(chunk.content) > 300 else chunk.content)
#         print(f"\nMetadata Keys: {list(chunk.metadata.keys())}")
#         print()
    
#     # ========================================================================
#     # STEP 3: VECTOR STORE
#     # ========================================================================
#     print_step(3, "VECTOR STORE", "Generate embeddings and store chunks in ChromaDB")
    
#     print_input("Chunks to Store", f"{len(chunks)} Chunk objects")
#     print_input("Persist Directory", str(persist_dir))
#     print_input("Collection Name", "property_listings")
#     print_input("Embedding Model", "all-MiniLM-L6-v2")
    
#     print("🔄 Processing: Initializing vector store...")
#     vector_store = PropertyVectorStore(
#         collection_name="property_listings",
#         persist_directory=str(persist_dir),
#         embedding_model="all-MiniLM-L6-v2"
#     )
    
#     print("🔄 Processing: Generating embeddings and storing chunks...")
#     # Only add chunks if collection is empty (to avoid duplicates in demo)
#     info = vector_store.get_collection_info()
#     if info['chunk_count'] == 0:
#         print("   (Collection is empty, adding chunks...)")
#         # For demo, we'll add chunks from all listings
#         print("   Loading all listings and chunking...")
#         formatted_listings = [format_listing_for_chunking(listing) for listing in raw_listings]
#         all_chunks = chunker.chunk_all_listings(formatted_listings)
#         print(f"   Created {len(all_chunks)} total chunks from {len(raw_listings)} listings")
#         vector_store.add_chunks(all_chunks)
#     else:
#         print(f"   (Collection already has {info['chunk_count']} chunks, skipping add)")
    
#     collection_info = vector_store.get_collection_info()
#     print_output("Vector Store Info", collection_info)
    
#     # Test search
#     print("\n🔍 Testing Vector Store Search:")
#     print("─" * 80)
#     test_query = "3 bedroom apartment"
#     print(f"Test Query: '{test_query}'")
#     search_results = vector_store.search(query=test_query, n_results=3)
#     print(f"Results Found: {len(search_results)}")
#     if search_results:
#         print(f"\nTop Result:")
#         print(f"  Chunk ID: {search_results[0]['id']}")
#         print(f"  Chunk Type: {search_results[0]['metadata'].get('chunk_type', 'N/A')}")
#         print(f"  Distance: {search_results[0].get('distance', 'N/A')}")
#         print(f"  Content Preview: {search_results[0]['content'][:200]}...")
    
#     return vector_store


# def demo_rag_pipeline(vector_store: PropertyVectorStore = None):
#     """Demonstrate the complete RAG pipeline."""
#     print_section("RAG PIPELINE", "=", 80)
    
#     # Setup
#     persist_dir = project_root / "chroma_db"
    
#     # Example enquiry
#     example_enquiry = BuyerEnquiry(
#         question="What is the price of properties with 3 bedrooms?",
#         listing_id=None,
#         user_id="demo_user_123",
#         session_id="demo_session_456"
#     )
    
#     # ========================================================================
#     # STEP 1: PREPROCESS
#     # ========================================================================
#     print_step(1, "PREPROCESS", "Normalize and extract information from buyer enquiry")
    
#     print_input("Buyer Enquiry", {
#         "question": example_enquiry.question,
#         "listing_id": example_enquiry.listing_id,
#         "user_id": example_enquiry.user_id,
#         "session_id": example_enquiry.session_id
#     })
    
#     print("🔄 Processing: Preprocessing enquiry...")
#     preprocessed = preprocess_enquiry(example_enquiry)
    
#     print_output("Preprocessed Enquiry", preprocessed)
    
#     # Detect enquiry type
#     enquiry_type = detect_enquiry_type(example_enquiry.question)
#     print_info("Detected Enquiry Type", enquiry_type)
    
#     # ========================================================================
#     # STEP 2: RETRIEVAL
#     # ========================================================================
#     print_step(2, "RETRIEVAL", "Search vector store for relevant property listing chunks")
    
#     query = preprocessed["normalized_query"]
#     print_input("Query", query)
#     print_input("Number of Results", 5)
#     print_input("Listing ID Filter", preprocessed.get("listing_id") or "None")
    
#     print("🔄 Processing: Initializing retriever...")
#     retriever = PropertyRetriever(
#         vector_store=vector_store,
#         collection_name="property_listings",
#         persist_directory=str(persist_dir),
#         use_hybrid_retrieval=True
#     )
    
#     print("🔄 Processing: Detecting query intent...")
#     intent_scores = retriever.detect_query_intent(query)
#     print_output("Query Intent Scores", intent_scores)
    
#     print("🔄 Processing: Retrieving relevant chunks...")
#     retrieval_results = retriever.retrieve(
#         query=query,
#         n_results=5,
#         listing_id=preprocessed.get("listing_id")
#     )
    
#     print_output(f"Retrieval Results (count: {len(retrieval_results)})", 
#                  f"List of {len(retrieval_results)} result dictionaries")
    
#     # Show retrieval results
#     print("\n📋 Retrieval Results Details:")
#     print("─" * 80)
#     for i, result in enumerate(retrieval_results[:3]):  # Show first 3
#         print(f"\nResult {i+1}:")
#         print(f"  ID: {result.get('id', 'N/A')}")
#         print(f"  Chunk Type: {result.get('metadata', {}).get('chunk_type', 'N/A')}")
#         print(f"  Listing ID: {result.get('metadata', {}).get('listing_id', 'N/A')}")
#         print(f"  Distance: {result.get('distance', 'N/A'):.4f}")
#         print(f"  Content Preview: {result.get('content', '')[:200]}...")
    
#     # ========================================================================
#     # STEP 3: AUGMENTATION
#     # ========================================================================
#     print_step(3, "AUGMENTATION", "Enrich query with retrieved context and format for LLM")
    
#     print_input("Query", query)
#     print_input("Retrieval Results", f"{len(retrieval_results)} results")
    
#     print("🔄 Processing: Augmenting query with context...")
#     augmenter = QueryAugmenter(
#         retriever=retriever,
#         collection_name="property_listings",
#         persist_directory=str(persist_dir)
#     )
    
#     augmented_context, data_sources = augmenter.augment_query(
#         query=query,
#         listing_id=preprocessed.get("listing_id"),
#         n_results=5
#     )
    
#     print_output("Augmented Context", augmented_context[:1000] + "..." if len(augmented_context) > 1000 else augmented_context)
#     print_info("Context Length", f"{len(augmented_context)} characters")
    
#     print_output(f"Data Sources (count: {len(data_sources)})", [
#         {
#             "chunk_type": ds.chunk_type,
#             "listing_id": ds.listing_id,
#             "similarity_score": ds.similarity_score
#         }
#         for ds in data_sources[:3]  # Show first 3
#     ])
    
#     # Check data sufficiency
#     print("🔄 Processing: Checking data sufficiency...")
#     is_sufficient, reason = augmenter.check_data_sufficiency(
#         query=query,
#         retrieved_context=augmented_context,
#         data_sources=data_sources
#     )
#     print_output("Data Sufficiency Check", {
#         "is_sufficient": is_sufficient,
#         "reason": reason or "Data is sufficient"
#     })
    
#     # ========================================================================
#     # STEP 4: GENERATION
#     # ========================================================================
#     print_step(4, "GENERATION", "Generate AI response using LLM with retrieved context")
    
#     print_input("Query", query)
#     print_input("Augmented Context", f"{len(augmented_context)} characters")
#     print_input("Data Sources", f"{len(data_sources)} sources")
    
#     print("🔄 Processing: Initializing response generator...")
#     generator = ResponseGenerator(
#         augmenter=augmenter,
#         collection_name="property_listings",
#         persist_directory=str(persist_dir)
#     )
    
#     print("🔄 Processing: Generating AI response with LLM...")
#     print("   (This may take a few seconds...)")
    
#     try:
#         result = generator.generate_response_from_enquiry(preprocessed)
        
#         ai_response = result["ai_response"]
#         log_entry = result["log_entry"]
        
#         print_output("AI Response", {
#             "answer_length": len(ai_response.answer),
#             "needs_vendor_contact": ai_response.needs_vendor_contact,
#             "escalation_reason": ai_response.escalation_reason,
#             "data_sources_count": len(ai_response.data_sources),
#             "has_disclaimer": "disclaimer" in ai_response.answer.lower()
#         })
        
#         print("\n📝 AI Response Answer:")
#         print("─" * 80)
#         print(ai_response.answer[:800] + "..." if len(ai_response.answer) > 800 else ai_response.answer)
#         print()
        
#         print_output("Log Entry", {
#             "id": log_entry.id,
#             "timestamp": str(log_entry.timestamp),
#             "question": log_entry.question[:100] + "..." if len(log_entry.question) > 100 else log_entry.question,
#             "model_version": log_entry.model_version
#         })
        
#     except Exception as e:
#         print(f"❌ ERROR during generation: {e}")
#         print("   (This might be due to missing API keys or network issues)")
#         import traceback
#         traceback.print_exc()
#         return None
    
#     # ========================================================================
#     # STEP 5: POSTPROCESS
#     # ========================================================================
#     print_step(5, "POSTPROCESS", "Validate, sanitize, and format response for API")
    
#     print_input("AI Response", {
#         "answer_length": len(ai_response.answer),
#         "needs_vendor_contact": ai_response.needs_vendor_contact,
#         "data_sources_count": len(ai_response.data_sources)
#     })
    
#     print("🔄 Processing: Validating response...")
#     is_valid, error_msg = validate_response(ai_response)
#     print_output("Validation Result", {
#         "is_valid": is_valid,
#         "error_message": error_msg or "Response is valid"
#     })
    
#     print("🔄 Processing: Sanitizing response (content safety check)...")
#     sanitized_response = sanitize_response(ai_response)
#     print_info("Sanitization", "Response sanitized (harmful content filtered if detected)")
    
#     print("🔄 Processing: Formatting for API...")
#     api_response = format_response_for_api(
#         ai_response=sanitized_response,
#         log_entry=log_entry
#     )
    
#     print_output("Final API Response", {
#         "answer_length": len(api_response.get("answer", "")),
#         "needs_vendor_contact": api_response.get("needs_vendor_contact"),
#         "data_sources_count": len(api_response.get("data_sources", [])),
#         "has_disclaimer": "disclaimer" in api_response.get("answer", "").lower(),
#         "log_id": api_response.get("log_id"),
#         "timestamp": api_response.get("timestamp")
#     })
    
#     print("\n📋 Final API Response Structure:")
#     print("─" * 80)
#     print(json.dumps({
#         "answer": api_response.get("answer", "")[:500] + "..." if len(api_response.get("answer", "")) > 500 else api_response.get("answer", ""),
#         "needs_vendor_contact": api_response.get("needs_vendor_contact"),
#         "data_sources_count": len(api_response.get("data_sources", [])),
#         "disclaimer": "..." if api_response.get("disclaimer") else None
#     }, indent=2))
    
#     return api_response


# def demo_evaluation_pipeline(vector_store: PropertyVectorStore = None):
#     """Demonstrate the evaluation pipeline."""
#     print_section("EVALUATION PIPELINE", "=", 80)
    
#     # Setup
#     persist_dir = project_root / "chroma_db"
    
#     # ========================================================================
#     # STEP 1: INITIALIZE EVALUATOR
#     # ========================================================================
#     print_step(1, "INITIALIZE EVALUATOR", "Set up evaluator with generator and retriever")
    
#     print_input("Vector Store", "PropertyVectorStore instance" if vector_store else "Will create new")
#     print_input("Collection Name", "property_listings")
#     print_input("Persist Directory", str(persist_dir))
    
#     print("🔄 Processing: Initializing evaluator...")
#     evaluator = RAGEvaluator(
#         collection_name="property_listings",
#         persist_directory=str(persist_dir)
#     )
    
#     print_output("Evaluator", {
#         "generator": "ResponseGenerator initialized",
#         "retriever": "PropertyRetriever initialized"
#     })
    
#     # ========================================================================
#     # STEP 2: PREPARE TEST CASES
#     # ========================================================================
#     print_step(2, "PREPARE TEST CASES", "Define test cases with queries and expected outcomes")
    
#     test_cases = get_default_test_cases()
#     print_input("Test Cases", f"{len(test_cases)} test cases")
    
#     print("\n📋 Test Cases Details:")
#     print("─" * 80)
#     for i, test_case in enumerate(test_cases, 1):
#         print(f"\nTest Case {i}:")
#         print(f"  Query: {test_case.query}")
#         print(f"  Category: {test_case.category}")
#         print(f"  Expected Keywords: {test_case.expected_keywords or 'None'}")
#         print(f"  Expected Chunk Types: {test_case.expected_chunk_types or 'None'}")
    
#     print_output("Test Cases Summary", {
#         "total_cases": len(test_cases),
#         "categories": list(set(tc.category for tc in test_cases))
#     })
    
#     # ========================================================================
#     # STEP 3: RUN EVALUATIONS
#     # ========================================================================
#     print_step(3, "RUN EVALUATIONS", "Evaluate each test case and calculate metrics")
    
#     print_input("Evaluation Parameters", {
#         "k": 5,  # Number of results to consider
#         "test_cases": len(test_cases)
#     })
    
#     print("🔄 Processing: Running evaluations...")
#     print("   (This may take a few minutes depending on LLM response times...)")
    
#     try:
#         summary = evaluator.evaluate(test_cases, k=5)
        
#         print_output("Evaluation Complete", {
#             "total_cases": summary.total_cases,
#             "successful_cases": summary.successful_cases,
#             "failed_cases": summary.failed_cases,
#             "success_rate": f"{(summary.successful_cases / summary.total_cases * 100):.1f}%" if summary.total_cases > 0 else "0%"
#         })
        
#     except Exception as e:
#         print(f"❌ ERROR during evaluation: {e}")
#         print("   (This might be due to missing API keys or network issues)")
#         import traceback
#         traceback.print_exc()
#         return None
    
#     # ========================================================================
#     # STEP 4: DISPLAY METRICS
#     # ========================================================================
#     print_step(4, "DISPLAY METRICS", "Show retrieval, generation, and overall metrics")
    
#     print_input("Evaluation Summary", "Summary object with all metrics")
    
#     print("🔄 Processing: Calculating and displaying metrics...")
    
#     # Print summary using evaluator's method
#     evaluator.print_summary(summary)
    
#     # Show detailed results for first successful case
#     successful_results = [r for r in summary.results if r.error is None]
#     if successful_results:
#         print("\n📊 Detailed Results for First Successful Test Case:")
#         print("─" * 80)
#         result = successful_results[0]
        
#         print(f"\nQuery: {result.test_case.query}")
#         print(f"Category: {result.test_case.category}")
        
#         print(f"\n🔍 Retrieval Metrics:")
#         print(f"  Precision@5: {result.retrieval_metrics.precision_at_k:.3f}")
#         print(f"  Recall@5: {result.retrieval_metrics.recall_at_k:.3f}")
#         print(f"  Mean Reciprocal Rank (MRR): {result.retrieval_metrics.mean_reciprocal_rank:.3f}")
#         print(f"  Hit Rate: {result.retrieval_metrics.hit_rate:.3f}")
#         print(f"  Average Similarity: {result.retrieval_metrics.average_similarity_score:.3f}")
#         print(f"  Retrieval Time: {result.retrieval_metrics.retrieval_time_ms:.2f} ms")
#         print(f"  Number of Results: {result.retrieval_metrics.num_results}")
        
#         print(f"\n💬 Generation Metrics:")
#         print(f"  Relevance Score: {result.generation_metrics.relevance_score:.3f}")
#         print(f"  Factual Accuracy: {result.generation_metrics.factual_accuracy:.3f}")
#         print(f"  Completeness: {result.generation_metrics.completeness:.3f}")
#         print(f"  Format Compliance: {result.generation_metrics.format_compliance:.3f}")
#         print(f"  Disclaimer Present: {result.generation_metrics.disclaimer_present}")
#         print(f"  Has Main Answer: {result.generation_metrics.has_main_answer}")
#         print(f"  Has Supporting Details: {result.generation_metrics.has_supporting_details}")
#         print(f"  Answer Length: {result.generation_metrics.answer_length} characters")
#         print(f"  Generation Time: {result.generation_metrics.generation_time_ms:.2f} ms")
#         print(f"  Needs Vendor Contact: {result.generation_metrics.needs_vendor_contact}")
        
#         print(f"\n⏱️  Performance:")
#         print(f"  Total Time: {result.total_time_ms:.2f} ms")
        
#         if result.ai_response:
#             print(f"\n📝 Answer Preview (first 300 chars):")
#             print("─" * 80)
#             print(result.ai_response.answer[:300] + "..." if len(result.ai_response.answer) > 300 else result.ai_response.answer)
#             print()
            
#             print(f"📚 Data Sources Used: {len(result.ai_response.data_sources)}")
#             for i, ds in enumerate(result.ai_response.data_sources[:3], 1):
#                 print(f"  {i}. {ds.chunk_type} (Listing: {ds.listing_id[:20]}..., Similarity: {ds.similarity_score:.3f})")
    
#     # Show failed cases if any
#     failed_results = [r for r in summary.results if r.error is not None]
#     if failed_results:
#         print("\n❌ Failed Test Cases:")
#         print("─" * 80)
#         for result in failed_results:
#             print(f"\nQuery: {result.test_case.query}")
#             print(f"Error: {result.error}")
    
#     # Show category-specific metrics
#     if summary.category_metrics:
#         print("\n📁 Category-Specific Performance:")
#         print("─" * 80)
#         for category, metrics in summary.category_metrics.items():
#             print(f"\n{category.upper()}:")
#             print(f"  Test Cases: {metrics['count']}")
#             print(f"  Avg Precision: {metrics['avg_precision']:.3f}")
#             print(f"  Avg Recall: {metrics['avg_recall']:.3f}")
#             print(f"  Avg Relevance: {metrics['avg_relevance']:.3f}")
#             print(f"  Avg Completeness: {metrics['avg_completeness']:.3f}")
    
#     return summary


# def main():
#     """Main function to run the complete pipeline demonstration."""
#     print_section("COMPLETE PIPELINE DEMONSTRATION", "=", 80)
#     print("This script demonstrates each step of both pipelines with actual inputs and outputs.")
#     print("Run from project root: python scripts/demo_pipeline_steps.py\n")
    
#     try:
#         # Run Data Ingestion Pipeline
#         vector_store = demo_data_ingestion_pipeline()
        
#         if vector_store is None:
#             print("\n❌ Data ingestion pipeline failed. Cannot continue with RAG pipeline.")
#             return
        
#         # Run RAG Pipeline
#         api_response = demo_rag_pipeline(vector_store)
        
#         if api_response:
#             # Run Evaluation Pipeline
#             evaluation_summary = demo_evaluation_pipeline(vector_store)
            
#             print_section("DEMONSTRATION COMPLETE", "=", 80)
#             print("✅ All pipeline steps executed successfully!")
#             print("\nSummary:")
#             print(f"  - Data Ingestion: ✅ Complete")
#             print(f"  - RAG Pipeline: ✅ Complete")
#             print(f"  - Final Response: ✅ Generated")
#             if evaluation_summary:
#                 print(f"  - Evaluation: ✅ Complete ({evaluation_summary.successful_cases}/{evaluation_summary.total_cases} successful)")
#                 print(f"\n📊 Evaluation Highlights:")
#                 print(f"    - Avg Precision@5: {evaluation_summary.avg_precision_at_k:.3f}")
#                 print(f"    - Avg Relevance: {evaluation_summary.avg_relevance_score:.3f}")
#                 print(f"    - Avg Completeness: {evaluation_summary.avg_completeness:.3f}")
#                 print(f"    - Format Compliance: {evaluation_summary.avg_format_compliance:.3f}")
#             else:
#                 print(f"  - Evaluation: ⚠️  Completed with warnings")
#         else:
#             print("\n⚠️  RAG pipeline completed with warnings (check LLM configuration)")
#             print("   Skipping evaluation pipeline...")
            
#     except Exception as e:
#         print(f"\n❌ ERROR: {e}")
#         import traceback
#         traceback.print_exc()


# if __name__ == "__main__":
#     main()

