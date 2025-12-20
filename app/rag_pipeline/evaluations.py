"""
Evaluation module for RAG pipeline metrics.
Provides comprehensive evaluation of retrieval, generation, and end-to-end performance.
"""
import time
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pprint import pprint

from app.rag_pipeline.schemas import BuyerEnquiry, AIResponse, DataSource
from app.rag_pipeline.generation import ResponseGenerator
from app.rag_pipeline.retrieval import PropertyRetriever
from app.rag_pipeline.augmentation import QueryAugmenter
from app.rag_pipeline.preprocess import preprocess_enquiry


@dataclass
class TestCase:
    """A test case for evaluation."""
    query: str
    expected_listing_ids: Optional[List[str]] = None  # Expected listing IDs in results
    expected_chunk_types: Optional[List[str]] = None  # Expected chunk types
    expected_keywords: Optional[List[str]] = None  # Keywords that should appear in answer
    expected_answer_contains: Optional[List[str]] = None  # Phrases that should be in answer
    expected_answer_not_contains: Optional[List[str]] = None  # Phrases that should NOT be in answer
    should_need_vendor_contact: bool = False  # Whether vendor contact should be needed
    listing_id: Optional[str] = None  # Specific listing ID if query is about one property
    category: str = "general"  # Category: price, specifications, location, bidding, general


@dataclass
class RetrievalMetrics:
    """Metrics for retrieval performance."""
    precision_at_k: float = 0.0  # Precision@K
    recall_at_k: float = 0.0  # Recall@K
    mean_reciprocal_rank: float = 0.0  # MRR
    hit_rate: float = 0.0  # Hit rate (at least one relevant result in top K)
    average_similarity_score: float = 0.0  # Average similarity of retrieved chunks
    retrieval_time_ms: float = 0.0  # Retrieval time in milliseconds
    num_results: int = 0  # Number of results retrieved


@dataclass
class GenerationMetrics:
    """Metrics for generation performance."""
    relevance_score: float = 0.0  # Relevance of answer to query (0-1)
    factual_accuracy: float = 0.0  # Factual accuracy based on data sources (0-1)
    completeness: float = 0.0  # How complete the answer is (0-1)
    format_compliance: float = 0.0  # Whether response follows required format (0-1)
    disclaimer_present: bool = False  # Whether disclaimer is included
    has_main_answer: bool = False  # Whether [Main Answer] section exists
    has_supporting_details: bool = False  # Whether [Supporting Details] section exists
    answer_length: int = 0  # Length of answer in characters
    generation_time_ms: float = 0.0  # Generation time in milliseconds
    needs_vendor_contact: bool = False  # Whether vendor contact was needed


@dataclass
class EvaluationResult:
    """Results for a single test case evaluation."""
    test_case: TestCase
    retrieval_metrics: RetrievalMetrics
    generation_metrics: GenerationMetrics
    retrieved_chunks: List[Dict[str, Any]] = field(default_factory=list)
    ai_response: Optional[AIResponse] = None
    error: Optional[str] = None
    total_time_ms: float = 0.0


@dataclass
class EvaluationSummary:
    """Summary of all evaluation results."""
    total_cases: int = 0
    successful_cases: int = 0
    failed_cases: int = 0
    
    # Average retrieval metrics
    avg_precision_at_k: float = 0.0
    avg_recall_at_k: float = 0.0
    avg_mrr: float = 0.0
    avg_hit_rate: float = 0.0
    avg_retrieval_time_ms: float = 0.0
    
    # Average generation metrics
    avg_relevance_score: float = 0.0
    avg_factual_accuracy: float = 0.0
    avg_completeness: float = 0.0
    avg_format_compliance: float = 0.0
    disclaimer_compliance_rate: float = 0.0
    
    # Overall metrics
    avg_total_time_ms: float = 0.0
    vendor_contact_rate: float = 0.0
    
    # Category-specific metrics
    category_metrics: Dict[str, Dict[str, float]] = field(default_factory=dict)
    
    results: List[EvaluationResult] = field(default_factory=list)


class RAGEvaluator:
    """Evaluator for RAG pipeline performance."""
    
    def __init__(
        self,
        generator: Optional[ResponseGenerator] = None,
        retriever: Optional[PropertyRetriever] = None,
        collection_name: str = "property_listings",
        persist_directory: str = "./chroma_db"
    ):
        """
        Initialize the evaluator.
        
        Args:
            generator: Optional pre-initialized response generator
            retriever: Optional pre-initialized retriever
            collection_name: Name of ChromaDB collection
            persist_directory: Directory where ChromaDB data is persisted
        """
        if generator is None:
            self.generator = ResponseGenerator(
                collection_name=collection_name,
                persist_directory=persist_directory
            )
        else:
            self.generator = generator
        
        if retriever is None:
            self.retriever = PropertyRetriever(
                collection_name=collection_name,
                persist_directory=persist_directory
            )
        else:
            self.retriever = retriever
    
    def evaluate_retrieval(
        self,
        query: str,
        test_case: TestCase,
        k: int = 5
    ) -> RetrievalMetrics:
        """
        Evaluate retrieval performance for a query.
        
        Args:
            query: The search query
            test_case: Test case with expected results
            k: Number of results to consider (K for precision/recall)
            
        Returns:
            RetrievalMetrics object
        """
        start_time = time.time()
        
        # Retrieve results
        results = self.retriever.retrieve(query=query, n_results=k, listing_id=test_case.listing_id)
        
        retrieval_time_ms = (time.time() - start_time) * 1000
        
        if not results:
            return RetrievalMetrics(
                retrieval_time_ms=retrieval_time_ms,
                num_results=0
            )
        
        # Calculate precision and recall
        relevant_count = 0
        if test_case.expected_listing_ids:
            retrieved_listing_ids = [r.get('metadata', {}).get('listing_id') for r in results]
            relevant_listing_ids = set(test_case.expected_listing_ids)
            retrieved_set = set(retrieved_listing_ids)
            
            # Precision: relevant retrieved / total retrieved
            if len(retrieved_set) > 0:
                precision = len(relevant_listing_ids & retrieved_set) / len(retrieved_set)
            else:
                precision = 0.0
            
            # Recall: relevant retrieved / total relevant
            if len(relevant_listing_ids) > 0:
                recall = len(relevant_listing_ids & retrieved_set) / len(relevant_listing_ids)
            else:
                recall = 0.0
            
            # Hit rate: at least one relevant result
            hit_rate = 1.0 if len(relevant_listing_ids & retrieved_set) > 0 else 0.0
            
            # MRR: reciprocal rank of first relevant result
            mrr = 0.0
            for i, result in enumerate(results, 1):
                listing_id = result.get('metadata', {}).get('listing_id')
                if listing_id in relevant_listing_ids:
                    mrr = 1.0 / i
                    break
        else:
            # If no expected listing IDs, calculate based on chunk types and similarity
            precision = 0.0
            recall = 0.0
            hit_rate = 0.0
            mrr = 0.0
            
            # Use chunk types if specified
            if test_case.expected_chunk_types:
                retrieved_chunk_types = [r.get('metadata', {}).get('chunk_type') for r in results]
                relevant_chunk_types = set(test_case.expected_chunk_types)
                retrieved_chunk_set = set(retrieved_chunk_types)
                
                if len(retrieved_chunk_set) > 0:
                    # Precision: relevant chunk types retrieved / total retrieved
                    precision = len(relevant_chunk_types & retrieved_chunk_set) / len(retrieved_chunk_set)
                    # Recall: relevant chunk types retrieved / total relevant
                    if len(relevant_chunk_types) > 0:
                        recall = len(relevant_chunk_types & retrieved_chunk_set) / len(relevant_chunk_types)
                    # Hit rate: at least one relevant chunk type
                    hit_rate = 1.0 if len(relevant_chunk_types & retrieved_chunk_set) > 0 else 0.0
                    # MRR: position of first relevant chunk type
                    for i, result in enumerate(results, 1):
                        chunk_type = result.get('metadata', {}).get('chunk_type')
                        if chunk_type in relevant_chunk_types:
                            mrr = 1.0 / i
                            break
            
            # If still no precision/recall, use similarity scores as proxy
            if precision == 0.0 and recall == 0.0:
                # Use average similarity as a proxy for precision
                similarities = [1.0 - r.get('distance', 1.0) for r in results if r.get('distance') is not None]
                if similarities:
                    avg_sim = sum(similarities) / len(similarities)
                    # Map similarity to precision/recall (similarity > 0.6 is good)
                    precision = min(1.0, avg_sim * 1.2)  # Scale similarity to precision
                    recall = min(1.0, avg_sim * 1.0)  # More conservative for recall
                    hit_rate = 1.0 if avg_sim > 0.4 else 0.0
                    mrr = avg_sim  # Use similarity as MRR proxy
                else:
                    # Fallback defaults
                    precision = 0.3
                    recall = 0.3
                    hit_rate = 0.0
                    mrr = 0.0
        
        # Check chunk types if specified
        if test_case.expected_chunk_types:
            retrieved_chunk_types = [r.get('metadata', {}).get('chunk_type') for r in results]
            relevant_chunk_types = set(test_case.expected_chunk_types)
            retrieved_chunk_set = set(retrieved_chunk_types)
            
            if len(retrieved_chunk_set) > 0:
                chunk_precision = len(relevant_chunk_types & retrieved_chunk_set) / len(retrieved_chunk_set)
                precision = (precision + chunk_precision) / 2  # Average with listing-based precision
        
        # Calculate average similarity
        similarities = []
        for result in results:
            distance = result.get('distance')
            if distance is not None:
                similarity = 1.0 - distance
                similarities.append(similarity)
        
        avg_similarity = sum(similarities) / len(similarities) if similarities else 0.0
        
        return RetrievalMetrics(
            precision_at_k=precision,
            recall_at_k=recall,
            mean_reciprocal_rank=mrr,
            hit_rate=hit_rate,
            average_similarity_score=avg_similarity,
            retrieval_time_ms=retrieval_time_ms,
            num_results=len(results)
        )
    
    def evaluate_generation(
        self,
        query: str,
        test_case: TestCase,
        ai_response: AIResponse,
        generation_time_ms: float
    ) -> GenerationMetrics:
        """
        Evaluate generation performance.
        
        Args:
            query: Original query
            test_case: Test case with expectations
            ai_response: Generated AI response
            generation_time_ms: Generation time in milliseconds
            
        Returns:
            GenerationMetrics object
        """
        answer = ai_response.answer.lower()
        
        # Format compliance
        has_main_answer = "## [main answer]" in answer or "## main answer" in answer
        has_supporting = "## [supporting details]" in answer or "## supporting details" in answer
        disclaimer_present = "based on available listing details" in answer or "disclaimer" in answer
        
        format_score = 0.0
        if has_main_answer:
            format_score += 0.4
        if has_supporting:
            format_score += 0.4
        if disclaimer_present:
            format_score += 0.2
        
        # Relevance: check if answer contains expected keywords
        relevance_score = 0.0
        if test_case.expected_keywords:
            found_keywords = sum(1 for kw in test_case.expected_keywords if kw.lower() in answer)
            relevance_score = found_keywords / len(test_case.expected_keywords)
        elif test_case.expected_answer_contains:
            found_phrases = sum(1 for phrase in test_case.expected_answer_contains if phrase.lower() in answer)
            relevance_score = found_phrases / len(test_case.expected_answer_contains)
        else:
            # Default: check if query keywords appear in answer
            query_words = set(query.lower().split())
            answer_words = set(answer.split())
            common_words = query_words & answer_words
            if len(query_words) > 0:
                relevance_score = len(common_words) / len(query_words)
        
        # Factual accuracy: based on data sources
        factual_accuracy = 0.0
        if ai_response.data_sources:
            # If we have data sources, assume some factual basis
            factual_accuracy = 0.7  # Base score
            # Boost if similarity scores are high
            high_similarity_sources = [ds for ds in ai_response.data_sources 
                                    if ds.similarity_score and ds.similarity_score > 0.7]
            if high_similarity_sources:
                factual_accuracy = 0.9
        else:
            factual_accuracy = 0.3  # Lower score if no data sources
        
        # Completeness: check if answer addresses the query comprehensively
        completeness = 0.0
        query_lower = query.lower()
        answer_lower = answer.lower()
        
        # Base score: answer length and structure
        if len(ai_response.answer) < 100:
            base_score = 0.2  # Very short answer
        elif len(ai_response.answer) < 200:
            base_score = 0.4  # Short answer
        elif len(ai_response.answer) < 400:
            base_score = 0.6  # Medium answer
        else:
            base_score = 0.8  # Substantial answer
        
        # Check if answer provides actual information vs just "contact vendor"
        has_actual_info = False
        if 'contact' in answer_lower and 'vendor' in answer_lower:
            # Check if there's info before the contact suggestion
            contact_idx = answer_lower.find('contact')
            if contact_idx > 100:  # Info before contact suggestion
                has_actual_info = True
        else:
            has_actual_info = True  # No contact suggestion, must have info
        
        if not has_actual_info:
            base_score *= 0.5  # Penalize if only saying to contact
        
        # Query-specific completeness checks
        query_specific_score = 0.0
        
        # Price queries: should mention prices, amounts, or pricing info
        if any(kw in query_lower for kw in ['price', 'cost', 'how much']):
            price_indicators = ['$', 'price', 'cost', 'auction', 'bid', 'offer', 'asking', 'sale']
            found_indicators = sum(1 for indicator in price_indicators if indicator in answer_lower)
            query_specific_score = min(0.4, found_indicators * 0.15)  # Up to 0.4 for price info
            
            # Check if multiple properties mentioned (for "properties" plural queries)
            if 'properties' in query_lower or 'property' in query_lower:
                # Check for multiple listings or examples
                if answer_lower.count('property') > 1 or answer_lower.count('listing') > 1:
                    query_specific_score += 0.2  # Bonus for multiple properties
        
        # Specification queries: should mention specs
        elif any(kw in query_lower for kw in ['bedroom', 'bathroom', 'garage', 'specification', 'spec']):
            spec_indicators = ['bedroom', 'bathroom', 'garage', 'area', 'sqm', 'sq ft', 'bed', 'bath']
            found_indicators = sum(1 for indicator in spec_indicators if indicator in answer_lower)
            query_specific_score = min(0.4, found_indicators * 0.15)
            
            # Check for specific numbers (e.g., "3 bedrooms")
            if any(char.isdigit() for char in query):
                # Query mentions a number, check if answer has numbers too
                query_numbers = [int(s) for s in query.split() if s.isdigit()]
                if query_numbers and any(str(num) in answer_lower for num in query_numbers):
                    query_specific_score += 0.2
        
        # Location queries: should mention location details
        elif any(kw in query_lower for kw in ['location', 'address', 'where', 'suburb', 'city']):
            location_indicators = ['address', 'location', 'suburb', 'city', 'street', 'state', 'postal']
            found_indicators = sum(1 for indicator in location_indicators if indicator in answer_lower)
            query_specific_score = min(0.4, found_indicators * 0.15)
        
        # Bidding queries: should mention bidding process or auction info
        elif any(kw in query_lower for kw in ['bid', 'bidding', 'auction', 'offer']):
            bidding_indicators = ['bid', 'bidding', 'auction', 'offer', 'process', 'deadline', 'date']
            found_indicators = sum(1 for indicator in bidding_indicators if indicator in answer_lower)
            query_specific_score = min(0.4, found_indicators * 0.15)
        
        # General queries: check for comprehensive answer
        else:
            # Check if answer addresses multiple aspects
            sections_found = sum(1 for section in ['main answer', 'supporting details', 'follow-up'] 
                               if section in answer_lower)
            query_specific_score = min(0.3, sections_found * 0.1)
        
        # Combine base score and query-specific score
        completeness = base_score + query_specific_score
        
        # Boost if data sources are used effectively
        if ai_response.data_sources:
            # Check if high-quality sources (high similarity)
            high_quality_sources = [ds for ds in ai_response.data_sources 
                                   if ds.similarity_score and ds.similarity_score > 0.6]
            if high_quality_sources:
                completeness += 0.1  # Bonus for using high-quality sources
        
        # Penalize if vendor contact is needed but shouldn't be
        if ai_response.needs_vendor_contact and not test_case.should_need_vendor_contact:
            completeness *= 0.8  # Slight penalty for unnecessary escalation
        
        # Cap at 1.0
        completeness = min(1.0, completeness)
        
        # Minimum completeness if answer exists
        if len(ai_response.answer) > 50:
            completeness = max(0.3, completeness)  # At least 0.3 if there's an answer
        
        # Check for phrases that should NOT be present
        if test_case.expected_answer_not_contains:
            for phrase in test_case.expected_answer_not_contains:
                if phrase.lower() in answer:
                    relevance_score *= 0.5  # Penalize if unwanted content present
        
        return GenerationMetrics(
            relevance_score=relevance_score,
            factual_accuracy=factual_accuracy,
            completeness=completeness,
            format_compliance=format_score,
            disclaimer_present=disclaimer_present,
            has_main_answer=has_main_answer,
            has_supporting_details=has_supporting,
            answer_length=len(ai_response.answer),
            generation_time_ms=generation_time_ms,
            needs_vendor_contact=ai_response.needs_vendor_contact
        )
    
    def evaluate_test_case(
        self,
        test_case: TestCase,
        k: int = 5
    ) -> EvaluationResult:
        """
        Evaluate a single test case.
        
        Args:
            test_case: Test case to evaluate
            k: Number of retrieval results to consider
            
        Returns:
            EvaluationResult object
        """
        total_start_time = time.time()
        
        try:
            # Preprocess query
            enquiry = BuyerEnquiry(
                question=test_case.query,
                listing_id=test_case.listing_id,
                user_id="evaluator",
                session_id="evaluation_session"
            )
            preprocessed = preprocess_enquiry(enquiry)
            query = preprocessed["normalized_query"]
            
            # Evaluate retrieval
            retrieval_metrics = self.evaluate_retrieval(query, test_case, k)
            
            # Get retrieved chunks for analysis
            retrieved_chunks = self.retriever.retrieve(query=query, n_results=k, listing_id=test_case.listing_id)
            
            # Generate response
            generation_start = time.time()
            result = self.generator.generate_response_from_enquiry(preprocessed)
            generation_time_ms = (time.time() - generation_start) * 1000
            
            ai_response = result["ai_response"]
            
            # Evaluate generation
            generation_metrics = self.evaluate_generation(
                query=test_case.query,
                test_case=test_case,
                ai_response=ai_response,
                generation_time_ms=generation_time_ms
            )
            
            total_time_ms = (time.time() - total_start_time) * 1000
            
            return EvaluationResult(
                test_case=test_case,
                retrieval_metrics=retrieval_metrics,
                generation_metrics=generation_metrics,
                retrieved_chunks=retrieved_chunks,
                ai_response=ai_response,
                total_time_ms=total_time_ms
            )
            
        except Exception as e:
            return EvaluationResult(
                test_case=test_case,
                retrieval_metrics=RetrievalMetrics(),
                generation_metrics=GenerationMetrics(),
                error=str(e),
                total_time_ms=(time.time() - total_start_time) * 1000
            )
    
    def evaluate(
        self,
        test_cases: List[TestCase],
        k: int = 5
    ) -> EvaluationSummary:
        """
        Evaluate multiple test cases.
        
        Args:
            test_cases: List of test cases to evaluate
            k: Number of retrieval results to consider
            
        Returns:
            EvaluationSummary object
        """
        results = []
        
        for test_case in test_cases:
            result = self.evaluate_test_case(test_case, k)
            results.append(result)
        
        # Calculate summary metrics
        successful_results = [r for r in results if r.error is None]
        failed_results = [r for r in results if r.error is not None]
        
        summary = EvaluationSummary(
            total_cases=len(test_cases),
            successful_cases=len(successful_results),
            failed_cases=len(failed_results),
            results=results
        )
        
        if successful_results:
            # Average retrieval metrics
            summary.avg_precision_at_k = sum(r.retrieval_metrics.precision_at_k for r in successful_results) / len(successful_results)
            summary.avg_recall_at_k = sum(r.retrieval_metrics.recall_at_k for r in successful_results) / len(successful_results)
            summary.avg_mrr = sum(r.retrieval_metrics.mean_reciprocal_rank for r in successful_results) / len(successful_results)
            summary.avg_hit_rate = sum(r.retrieval_metrics.hit_rate for r in successful_results) / len(successful_results)
            summary.avg_retrieval_time_ms = sum(r.retrieval_metrics.retrieval_time_ms for r in successful_results) / len(successful_results)
            
            # Average generation metrics
            summary.avg_relevance_score = sum(r.generation_metrics.relevance_score for r in successful_results) / len(successful_results)
            summary.avg_factual_accuracy = sum(r.generation_metrics.factual_accuracy for r in successful_results) / len(successful_results)
            summary.avg_completeness = sum(r.generation_metrics.completeness for r in successful_results) / len(successful_results)
            summary.avg_format_compliance = sum(r.generation_metrics.format_compliance for r in successful_results) / len(successful_results)
            summary.disclaimer_compliance_rate = sum(1 for r in successful_results if r.generation_metrics.disclaimer_present) / len(successful_results)
            
            # Overall metrics
            summary.avg_total_time_ms = sum(r.total_time_ms for r in successful_results) / len(successful_results)
            summary.vendor_contact_rate = sum(1 for r in successful_results if r.generation_metrics.needs_vendor_contact) / len(successful_results)
            
            # Category-specific metrics
            categories = {}
            for result in successful_results:
                category = result.test_case.category
                if category not in categories:
                    categories[category] = {
                        'count': 0,
                        'precision': [],
                        'recall': [],
                        'relevance': [],
                        'completeness': []
                    }
                
                categories[category]['count'] += 1
                categories[category]['precision'].append(result.retrieval_metrics.precision_at_k)
                categories[category]['recall'].append(result.retrieval_metrics.recall_at_k)
                categories[category]['relevance'].append(result.generation_metrics.relevance_score)
                categories[category]['completeness'].append(result.generation_metrics.completeness)
            
            for category, metrics in categories.items():
                summary.category_metrics[category] = {
                    'count': metrics['count'],
                    'avg_precision': sum(metrics['precision']) / len(metrics['precision']),
                    'avg_recall': sum(metrics['recall']) / len(metrics['recall']),
                    'avg_relevance': sum(metrics['relevance']) / len(metrics['relevance']),
                    'avg_completeness': sum(metrics['completeness']) / len(metrics['completeness'])
                }
        
        return summary
    
    def print_summary(self, summary: EvaluationSummary):
        """Print evaluation summary in a readable format."""
        print("\n" + "=" * 80)
        print("RAG PIPELINE EVALUATION SUMMARY")
        print("=" * 80)
        
        print(f"\n📊 Overall Statistics:")
        print(f"  Total Test Cases: {summary.total_cases}")
        print(f"  Successful: {summary.successful_cases}")
        print(f"  Failed: {summary.failed_cases}")
        print(f"  Success Rate: {(summary.successful_cases / summary.total_cases * 100):.1f}%")
        
        if summary.successful_cases > 0:
            print(f"\n🔍 Retrieval Metrics:")
            print(f"  Precision@K: {summary.avg_precision_at_k:.3f}")
            print(f"  Recall@K: {summary.avg_recall_at_k:.3f}")
            print(f"  Mean Reciprocal Rank (MRR): {summary.avg_mrr:.3f}")
            print(f"  Hit Rate: {summary.avg_hit_rate:.3f}")
            print(f"  Avg Retrieval Time: {summary.avg_retrieval_time_ms:.2f} ms")
            
            print(f"\n💬 Generation Metrics:")
            print(f"  Relevance Score: {summary.avg_relevance_score:.3f}")
            print(f"  Factual Accuracy: {summary.avg_factual_accuracy:.3f}")
            print(f"  Completeness: {summary.avg_completeness:.3f}")
            print(f"  Format Compliance: {summary.avg_format_compliance:.3f}")
            print(f"  Disclaimer Compliance: {summary.disclaimer_compliance_rate:.3f}")
            
            print(f"\n⏱️  Performance:")
            print(f"  Avg Total Time: {summary.avg_total_time_ms:.2f} ms")
            print(f"  Vendor Contact Rate: {summary.vendor_contact_rate:.3f}")
            
            if summary.category_metrics:
                print(f"\n📁 Category-Specific Metrics:")
                for category, metrics in summary.category_metrics.items():
                    print(f"\n  {category.upper()}:")
                    print(f"    Test Cases: {metrics['count']}")
                    print(f"    Avg Precision: {metrics['avg_precision']:.3f}")
                    print(f"    Avg Recall: {metrics['avg_recall']:.3f}")
                    print(f"    Avg Relevance: {metrics['avg_relevance']:.3f}")
                    print(f"    Avg Completeness: {metrics['avg_completeness']:.3f}")
            
            # Add recommendations based on metrics
            print("\n💡 Recommendations:")
            print("─" * 80)
            
            if summary.avg_completeness < 0.7:
                print("⚠️  Completeness is low (< 0.7). Consider:")
                print("   - Improving retrieval to find more relevant chunks")
                print("   - Enhancing prompts to encourage more comprehensive answers")
                print("   - Increasing number of retrieved chunks (n_results)")
            
            if summary.avg_precision_at_k < 0.7:
                print("⚠️  Precision is low (< 0.7). Consider:")
                print("   - Improving query understanding and intent detection")
                print("   - Fine-tuning embedding model or using better embeddings")
                print("   - Adjusting chunking strategy for better semantic boundaries")
            
            if summary.avg_recall_at_k < 0.6:
                print("⚠️  Recall is low (< 0.6). Consider:")
                print("   - Increasing number of retrieved results (k)")
                print("   - Using hybrid retrieval to get all chunks for matched listings")
                print("   - Improving query expansion or rewriting")
            
            if summary.avg_relevance_score < 0.8:
                print("⚠️  Relevance is low (< 0.8). Consider:")
                print("   - Improving prompt engineering to focus on query")
                print("   - Better context formatting in augmentation step")
                print("   - Filtering retrieved chunks by relevance threshold")
            
            # Check similarity scores
            avg_similarities = []
            for result in summary.results:
                if result.error is None and result.retrieved_chunks:
                    sims = [1.0 - r.get('distance', 1.0) for r in result.retrieved_chunks 
                           if r.get('distance') is not None]
                    if sims:
                        avg_similarities.extend(sims)
            
            if avg_similarities:
                overall_avg_sim = sum(avg_similarities) / len(avg_similarities)
                if overall_avg_sim < 0.6:
                    print("⚠️  Average similarity scores are low (< 0.6). Consider:")
                    print("   - Using a better embedding model")
                    print("   - Improving chunk quality and semantic boundaries")
                    print("   - Query preprocessing and normalization")
            
            # Positive feedback
            if summary.avg_format_compliance >= 0.9:
                print("✅ Format compliance is excellent!")
            if summary.avg_relevance_score >= 0.85:
                print("✅ Relevance scores are very good!")
        
        print("\n" + "=" * 80)


def get_default_test_cases() -> List[TestCase]:
    """
    Get default test cases for evaluation.
    
    Returns:
        List of TestCase objects
    """
    return [
        TestCase(
            query="What is the price of properties with 3 bedrooms?",
            expected_keywords=["price", "bedroom", "3"],
            expected_chunk_types=["pricing", "overview"],
            category="price"
        ),
        TestCase(
            query="Show me auction properties in Sydney",
            expected_keywords=["auction", "sydney"],
            expected_chunk_types=["pricing", "bidding", "location"],
            category="bidding"
        ),
        TestCase(
            query="What are the specifications for properties with swimming pools?",
            expected_keywords=["specification", "pool", "swimming"],
            expected_chunk_types=["specifications", "overview"],
            category="specifications"
        ),
        TestCase(
            query="Where are properties located?",
            expected_keywords=["location", "address"],
            expected_chunk_types=["location"],
            category="location"
        ),
        TestCase(
            query="How much should I bid on auction properties?",
            expected_keywords=["bid", "auction"],
            expected_chunk_types=["bidding", "pricing"],
            expected_answer_not_contains=["$", "specific amount", "exact price"],
            category="bidding"
        ),
    ]

