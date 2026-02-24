from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import asyncio

from app.eval.judge import LLMJudge
from app.eval.metrics import (
    classification_metrics,
    feature_alignment_checks,
    format_check,
    robustness_group_metrics,
)
from app.eval.mlflow_utils import init_mlflow, start_eval_run
from app.eval.timing import time_call
from app.helpers.ingestion_pipeline.property.pgvector_store import PgVectorStore
from app.services.rag_pipeline.generation import ResponseGenerator
from app.services.rag_pipeline.retrieval import PropertyRetriever


def load_examples(path: Path) -> List[Dict[str, Any]]:
    """
    Load evaluation examples from a JSON or JSONL file.

    Expected schema (flexible / best-effort):
      - id: unique identifier (string or int)
      - query: user query text
      - listing_id: optional listing ID
      - reference_answer: optional ground-truth answer
      - labels: optional list/sequence of labels for classification metrics
      - task_type: optional string, used by feature_alignment_checks
      - group_id: optional string for robustness groups (paraphrases of same intent)
      - json_schema: optional JSON schema for format validation (string or object)
    """
    text = path.read_text(encoding="utf-8")

    # Try JSONL first (one JSON object per non-empty, non-comment line)
    examples: List[Dict[str, Any]] = []
    try:
        lines = [l for l in text.splitlines() if l.strip()]
        for line in lines:
            stripped = line.lstrip()
            # Allow // or # comments in JSONL files for convenience
            if stripped.startswith("//") or stripped.startswith("#"):
                continue
            examples.append(json.loads(line))
        if examples:
            return examples
    except json.JSONDecodeError:
        # Fall back to parsing as a single JSON document below
        pass

    # Fallback to JSON array
    data = json.loads(text)
    if isinstance(data, list):
        return data
    raise ValueError(f"Unrecognised dataset format at {path}")


def benchmark_embeddings_for_dataset(chunks: List[Any]) -> Dict[str, float]:
    """
    Convenience wrapper to benchmark embeddings/ingestion latency for a list of Chunk objects.
    """
    if not chunks:
        return {"emb_total_ms": 0.0, "emb_per_chunk_ms": 0.0, "emb_chunks": 0.0}

    store = PgVectorStore()
    (_, emb_ms) = time_call(store.add_chunks, chunks)

    total_chunks = len(chunks)
    emb_per_chunk_ms = emb_ms / float(total_chunks)

    return {
        "emb_total_ms": float(emb_ms),
        "emb_per_chunk_ms": float(emb_per_chunk_ms),
        "emb_chunks": float(total_chunks),
    }


def evaluate_single_example(
    example: Dict[str, Any],
    judge: LLMJudge,
) -> Dict[str, Any]:
    """
    Run a single end-to-end evaluation, logging metrics to MLflow and
    returning a summary dict for in-memory aggregation.
    """
    query: str = example["query"]
    listing_id: Optional[str] = example.get("listing_id")
    example_id = str(example.get("id", query[:32]))

    # Optional JSON schema can be provided either as an object or as JSON string
    json_schema: Optional[Dict[str, Any]] = None
    raw_schema = example.get("json_schema")
    if isinstance(raw_schema, str):
        try:
            json_schema = json.loads(raw_schema)
        except json.JSONDecodeError:
            json_schema = None
    elif isinstance(raw_schema, dict):
        json_schema = raw_schema

    with start_eval_run(
        run_name=f"eval_{example_id}",
        tags={
            "stage": "inference",
            "task": example.get("task_type") or "chat_rag",
        },
    ):
        generator = ResponseGenerator()

        # End-to-end latency (and pipeline retrieval/LLM breakdown from generator)
        (response, total_ms) = time_call(
            asyncio.run(generator.generate_response),
            query=query,
            listing_id=listing_id,
            conversation_history=example.get("conversation_history"),
            n_retrieval_results=example.get("n_retrieval_results", 8),
        )
        eval_timings = response.get("eval_timings") or {}
        retrieval_pipeline_ms = eval_timings.get("retrieval_ms")
        llm_ms = eval_timings.get("llm_ms")
        total_pipeline_ms = eval_timings.get("total_ms")
        if retrieval_pipeline_ms is None:
            retrieval_pipeline_ms = 0.0
        if llm_ms is None:
            llm_ms = 0.0
        if total_pipeline_ms is None:
            total_pipeline_ms = total_ms

        # Embedding generation latency (query embed only)
        retriever = PropertyRetriever()
        _, embedding_ms = time_call(
            lambda: retriever.vector_store.embedding_model.encode([query], convert_to_numpy=False),
        )

        # Extract answer text robustly
        ai_resp = response.get("ai_response")
        answer_text = None
        if ai_resp is not None:
            answer_text = getattr(ai_resp, "answer", None)
            if answer_text is None:
                # Fall back to string representation
                answer_text = str(ai_resp)
        else:
            answer_text = ""

        # For judge context, run an explicit retrieval call (does not affect prod pipeline)
        if listing_id:
            (retrieval_out, retrieval_ms) = time_call(
                retriever.retrieve_with_location_context,
                query=query,
                listing_id=listing_id,
                n_results=example.get("n_retrieval_results", 8),
            )
            retr_results = retrieval_out[0]
            retr_location_context = retrieval_out[1]
        else:
            (retr_results, retrieval_ms) = ([], 0.0)
            retr_location_context = None

        # MLflow: latency metrics (all four + fine-grained breakdown)
        import mlflow

        mlflow.log_metric("latency_embedding_ms", float(embedding_ms))
        mlflow.log_metric("latency_retrieval_ms", float(retrieval_pipeline_ms))
        mlflow.log_metric("latency_llm_ms", float(llm_ms))
        mlflow.log_metric("latency_total_ms", float(total_pipeline_ms))
        breakdown = eval_timings.get("breakdown") or {}
        for k, v in breakdown.items():
            if isinstance(v, (int, float)):
                mlflow.log_metric(f"breakdown_{k}", float(v))

        # Basic params
        mlflow.log_param("example_id", example_id)
        mlflow.log_param("listing_id", listing_id or "none")
        mlflow.log_param("query", query)

        ref_answer = example.get("reference_answer")
        if ref_answer is not None:
            mlflow.log_param("reference_answer", ref_answer)

        # LLM-as-a-judge metrics
        judge_scores = judge.score(
            query=query,
            context={
                "retrieved_results": retr_results,
                "location_context": retr_location_context,
            },
            answer=answer_text or "",
            reference=ref_answer,
            guidelines=example.get("guidelines"),
        )
        for k, v in judge_scores.items():
            mlflow.log_metric(f"judge_{k}", float(v))

        # Feature alignment checks (code-based)
        feat_scores = feature_alignment_checks(example, answer_text or "")
        for k, v in feat_scores.items():
            mlflow.log_metric(f"feature_{k}", float(v))

        # Format / schema validation
        if json_schema:
            fmt_ok = format_check(answer_text or "", json_schema)
            mlflow.log_metric("format_valid", 1.0 if fmt_ok else 0.0)

        # Classification metrics, if labels are present
        labels = example.get("labels")
        pred_labels = example.get("pred_labels")
        class_scores: Dict[str, float] = {}
        if labels is not None and pred_labels is not None:
            try:
                class_scores = classification_metrics(labels, pred_labels)
                for k, v in class_scores.items():
                    mlflow.log_metric(f"class_{k}", float(v))
            except Exception:
                # Best-effort: classification metrics are optional
                class_scores = {}

        # Save raw artefacts for debugging
        mlflow.log_text(answer_text or "", "answer.txt")

        return {
            "id": example_id,
            "latency_embedding_ms": float(embedding_ms),
            "latency_retrieval_ms": float(retrieval_pipeline_ms),
            "latency_llm_ms": float(llm_ms),
            "latency_total_ms": float(total_pipeline_ms),
            "breakdown": breakdown,
            "judge_scores": judge_scores,
            "feature_scores": feat_scores,
            "class_scores": class_scores,
            "group_id": example.get("group_id"),
        }


def run_eval(
    dataset_path: Path,
    tracking_uri: Optional[str] = None,
    experiment_name: Optional[str] = None,
) -> None:
    """
    Run end-to-end evaluation for all examples in the dataset and log
    both per-example and aggregate metrics to MLflow.
    """
    init_mlflow(tracking_uri=tracking_uri, experiment_name=experiment_name)

    examples = load_examples(dataset_path)
    judge = LLMJudge()

    # Per-example runs
    results: List[Dict[str, Any]] = []
    for ex in examples:
        res = evaluate_single_example(ex, judge)
        results.append(res)

    # Aggregate robustness metrics per paraphrase group
    by_group: Dict[str, List[float]] = {}
    for res in results:
        gid = res.get("group_id")
        if not gid:
            continue
        score = res.get("judge_scores", {}).get("correctness_accuracy")
        if score is None:
            continue
        by_group.setdefault(str(gid), []).append(float(score))

    with start_eval_run(
        run_name="aggregate_metrics",
        tags={"stage": "aggregate", "task": "chat_rag"},
    ):
        import mlflow

        # Aggregate latency metrics (for actual review)
        if results:
            n = len(results)
            mlflow.log_metric("latency_embedding_ms_mean", float(sum(r["latency_embedding_ms"] for r in results) / n))
            mlflow.log_metric("latency_retrieval_ms_mean", float(sum(r["latency_retrieval_ms"] for r in results) / n))
            mlflow.log_metric("latency_llm_ms_mean", float(sum(r["latency_llm_ms"] for r in results) / n))
            mlflow.log_metric("latency_total_ms_mean", float(sum(r["latency_total_ms"] for r in results) / n))

        # Print latency summary and fine-grained breakdown for actual review
        if results:
            n = len(results)
            emb = [r["latency_embedding_ms"] for r in results]
            ret = [r["latency_retrieval_ms"] for r in results]
            llm = [r["latency_llm_ms"] for r in results]
            tot = [r["latency_total_ms"] for r in results]
            print("\n--- Latency (ms) ---")
            print(f"  Embedding (query):   mean={sum(emb)/n:.1f}  min={min(emb):.1f}  max={max(emb):.1f}")
            print(f"  Retrieval:           mean={sum(ret)/n:.1f}  min={min(ret):.1f}  max={max(ret):.1f}")
            print(f"  LLM response:       mean={sum(llm)/n:.1f}  min={min(llm):.1f}  max={max(llm):.1f}")
            print(f"  End-to-end pipeline: mean={sum(tot)/n:.1f}  min={min(tot):.1f}  max={max(tot):.1f}")
            # Aggregate breakdown (mean over examples that have each key)
            all_breakdown_keys: Dict[str, List[float]] = {}
            for r in results:
                for k, v in (r.get("breakdown") or {}).items():
                    if isinstance(v, (int, float)):
                        all_breakdown_keys.setdefault(k, []).append(float(v))
            if all_breakdown_keys:
                print("\n--- Breakdown (mean ms) ---")
                for k in sorted(all_breakdown_keys.keys()):
                    vals = all_breakdown_keys[k]
                    mean_val = sum(vals) / len(vals)
                    count = len(vals)
                    print(f"  {k}: {mean_val:.1f}  (n={count})")
                for k, v in all_breakdown_keys.items():
                    mean_val = sum(v) / len(v)
                    mlflow.log_metric(f"breakdown_mean_{k}", float(mean_val))
            print("----------------------\n")

        for gid, scores in by_group.items():
            agg = robustness_group_metrics(scores)
            for k, v in agg.items():
                mlflow.log_metric(f"group_{gid}_{k}", float(v))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline evaluation runner for Unreserved RAG pipeline.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parent / "chat_eval.jsonl",
        help="Path to JSON or JSONL file with evaluation examples (default: app/eval/chat_eval.jsonl).",
    )
    parser.add_argument(
        "--tracking-uri",
        type=str,
        default=None,
        help="MLflow tracking URI (e.g. file:/tmp/mlruns).",
    )
    parser.add_argument(
        "--experiment",
        type=str,
        default=None,
        help="Optional MLflow experiment name (overrides default).",
    )

    args = parser.parse_args()
    run_eval(
        dataset_path=args.dataset,
        tracking_uri=args.tracking_uri,
        experiment_name=args.experiment,
    )


if __name__ == "__main__":
    main()

