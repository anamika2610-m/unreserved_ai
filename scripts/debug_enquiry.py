"""
Debug script to see what context is being retrieved and passed to LLM.
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.rag_pipeline.preprocess import preprocess_enquiry
from app.rag_pipeline.augmentation import QueryAugmenter
from app.rag_pipeline.schemas import BuyerEnquiry
from app.rag_pipeline.prompts import create_user_prompt


def main():
    """Debug the retrieval and context formatting."""
    print("=" * 70)
    print("Debug: Retrieval and Context Formatting")
    print("=" * 70)
    
    # Initialize augmenter
    augmenter = QueryAugmenter()
    
    # Test query
    query = "What is the price of properties with 3 bedrooms?"
    print(f"\nQuery: {query}\n")
    
    # Get context
    context, data_sources = augmenter.augment_query(query, n_results=5)
    
    print("=" * 70)
    print("RETRIEVED CONTEXT (what will be sent to LLM):")
    print("=" * 70)
    print(context)
    print("\n" + "=" * 70)
    print(f"Data Sources: {len(data_sources)}")
    for i, ds in enumerate(data_sources, 1):
        print(f"  {i}. {ds.chunk_type} - Listing: {ds.listing_id[:30]}... (similarity: {ds.similarity_score:.3f})")
    
    print("\n" + "=" * 70)
    print("FULL PROMPT (what LLM will see):")
    print("=" * 70)
    user_prompt = create_user_prompt(query, context)
    print(user_prompt[:2000] + "..." if len(user_prompt) > 2000 else user_prompt)


if __name__ == "__main__":
    main()

