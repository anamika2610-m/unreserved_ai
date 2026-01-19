"""
Script to run RAG pipeline evaluations.
Run from project root: python scripts/run_evaluations.py
"""
import os
import sys
from pathlib import Path

# Disable ChromaDB telemetry to avoid errors
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.rag_pipeline.evaluations import RAGEvaluator, TestCase, get_default_test_cases


def main():
    """Run RAG pipeline evaluations."""
    print("=" * 80)
    print("RAG Pipeline Evaluation")
    print("=" * 80)
    
    # Check if vector store is initialized
    from app.ingestion_pipeline.vector_store import PropertyVectorStore
    vector_store = PropertyVectorStore()
    info = vector_store.get_collection_info()
    
    if info['chunk_count'] == 0:
        print("\n❌ ERROR: Vector store is empty!")
        print("Please run: python scripts/initialize_vector_store.py")
        return
    
    print(f"\n✓ Vector store initialized ({info['chunk_count']} chunks)")
    
    # Initialize evaluator
    print("\nInitializing evaluator...")
    try:
        evaluator = RAGEvaluator()
        print("✓ Evaluator initialized")
    except Exception as e:
        print(f"❌ Error initializing evaluator: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Get test cases
    test_cases = get_default_test_cases()
    print(f"\n📋 Running {len(test_cases)} test cases...")
    
    # Run evaluations
    summary = evaluator.evaluate(test_cases, k=5)
    
    # Print summary
    evaluator.print_summary(summary)
    
    # Print detailed results for failed cases
    failed_results = [r for r in summary.results if r.error is not None]
    if failed_results:
        print("\n" + "=" * 80)
        print("FAILED TEST CASES")
        print("=" * 80)
        for result in failed_results:
            print(f"\nQuery: {result.test_case.query}")
            print(f"Error: {result.error}")
    
    # Print sample successful results
    successful_results = [r for r in summary.results if r.error is None]
    if successful_results:
        print("\n" + "=" * 80)
        print("SAMPLE RESULTS (First 2 Successful Cases)")
        print("=" * 80)
        for i, result in enumerate(successful_results[:2], 1):
            print(f"\n--- Test Case {i} ---")
            print(f"Query: {result.test_case.query}")
            print(f"Category: {result.test_case.category}")
            print(f"\nRetrieval Metrics:")
            print(f"  Precision@5: {result.retrieval_metrics.precision_at_k:.3f}")
            print(f"  Recall@5: {result.retrieval_metrics.recall_at_k:.3f}")
            print(f"  Hit Rate: {result.retrieval_metrics.hit_rate:.3f}")
            print(f"  Avg Similarity: {result.retrieval_metrics.average_similarity_score:.3f}")
            print(f"\nGeneration Metrics:")
            print(f"  Relevance: {result.generation_metrics.relevance_score:.3f}")
            print(f"  Factual Accuracy: {result.generation_metrics.factual_accuracy:.3f}")
            print(f"  Completeness: {result.generation_metrics.completeness:.3f}")
            print(f"  Format Compliance: {result.generation_metrics.format_compliance:.3f}")
            print(f"  Needs Vendor Contact: {result.generation_metrics.needs_vendor_contact}")
            print(f"\nPerformance:")
            print(f"  Total Time: {result.total_time_ms:.2f} ms")
            print(f"  Retrieval Time: {result.retrieval_metrics.retrieval_time_ms:.2f} ms")
            print(f"  Generation Time: {result.generation_metrics.generation_time_ms:.2f} ms")
            
            if result.ai_response:
                print(f"\nAnswer Preview (first 200 chars):")
                print(result.ai_response.answer[:200] + "...")
    
    print("\n" + "=" * 80)
    print("Evaluation Complete")
    print("=" * 80)


if __name__ == "__main__":
    main()

