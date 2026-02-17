from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

try:
    from jsonschema import ValidationError, validate  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    ValidationError = Exception  # type: ignore
    validate = None  # type: ignore

try:
    from sklearn.metrics import (  # type: ignore
        accuracy_score,
        f1_score,
        jaccard_score,
        precision_score,
        recall_score,
    )
except ImportError:  # pragma: no cover - optional dependency
    accuracy_score = recall_score = precision_score = f1_score = jaccard_score = None  # type: ignore


def feature_alignment_checks(example: Dict[str, Any], answer: str) -> Dict[str, float]:
    """
    Simple, code-based checks that outputs adhere to required formats or feature flags.

    This can be extended with project-specific rules. For now we include a few
    generic hooks that you can build on.
    """
    scores: Dict[str, float] = {}

    task_type = example.get("task_type")

    # Example: for tasks where price must not be leaked, check for '$'
    if task_type == "chat_price_hidden":
        contains_dollar = "$" in answer
        scores["no_price_leak"] = 1.0 if not contains_dollar else 0.0

    # Example: ensure non-empty answer for normal chat tasks
    if task_type == "chat_generic":
        scores["non_empty_answer"] = 1.0 if answer.strip() else 0.0

    return scores


def format_check(answer: str, schema: Optional[Dict[str, Any]]) -> bool:
    """
    Validate that `answer` is JSON and (optionally) conforms to a JSON schema.
    """
    if not schema:
        # If no schema is provided, we only check that it is valid JSON
        try:
            json.loads(answer)
            return True
        except json.JSONDecodeError:
            return False

    if validate is None:
        # jsonschema not installed: fall back to "best effort"
        try:
            json.loads(answer)
            return True
        except json.JSONDecodeError:
            return False

    try:
        obj = json.loads(answer)
        validate(instance=obj, schema=schema)
        return True
    except (json.JSONDecodeError, ValidationError):
        return False


def robustness_group_metrics(scores: Sequence[float], threshold: float = 0.7) -> Dict[str, float]:
    """
    Derive robustness metrics over a group of paraphrased queries.

    - robust_success_rate: fraction of examples with score >= threshold
    - robust_variance: variance of the scores
    """
    if not scores:
        return {"robust_success_rate": 0.0, "robust_variance": 1.0}

    n = float(len(scores))
    success = sum(1.0 for s in scores if s >= threshold) / n
    mean = sum(scores) / n
    var = sum((s - mean) ** 2 for s in scores) / n

    return {
        "robust_success_rate": success,
        "robust_variance": var,
    }


def jaccard_set(pred: Iterable[str], gold: Iterable[str]) -> float:
    """
    Jaccard index between two sets of labels.
    """
    p: Set[str] = set(pred)
    g: Set[str] = set(gold)
    if not p and not g:
        return 1.0
    inter = len(p & g)
    union = len(p | g)
    return float(inter) / float(union) if union else 0.0


def classification_metrics(y_true: Sequence[int], y_pred: Sequence[int]) -> Dict[str, float]:
    """
    Standard classification metrics for binary / multi-class cases.

    If scikit-learn is not installed, this function falls back to simple
    accuracy and Jaccard implementations.
    """
    y_true_list = list(y_true)
    y_pred_list = list(y_pred)

    if len(y_true_list) != len(y_pred_list) or not y_true_list:
        return {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "accuracy": 0.0,
            "jaccard": 0.0,
        }

    # Fallback implementation if sklearn is unavailable
    if accuracy_score is None:
        correct = sum(1 for t, p in zip(y_true_list, y_pred_list) if t == p)
        accuracy = float(correct) / float(len(y_true_list))

        # Simple Jaccard for binary case (assuming labels {0,1})
        tp = sum(1 for t, p in zip(y_true_list, y_pred_list) if t == p == 1)
        fp = sum(1 for t, p in zip(y_true_list, y_pred_list) if t == 0 and p == 1)
        fn = sum(1 for t, p in zip(y_true_list, y_pred_list) if t == 1 and p == 0)
        union = tp + fp + fn
        jaccard = float(tp) / float(union) if union else 0.0

        # Simple precision/recall/F1
        precision = float(tp) / float(tp + fp) if (tp + fp) else 0.0
        recall = float(tp) / float(tp + fn) if (tp + fn) else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )

        return {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "accuracy": accuracy,
            "jaccard": jaccard,
        }

    # Use sklearn when available
    return {
        "precision": float(precision_score(y_true_list, y_pred_list, zero_division=0)),
        "recall": float(recall_score(y_true_list, y_pred_list, zero_division=0)),
        "f1": float(f1_score(y_true_list, y_pred_list, zero_division=0)),
        "accuracy": float(accuracy_score(y_true_list, y_pred_list)),
        "jaccard": float(jaccard_score(y_true_list, y_pred_list, zero_division=0)),
    }

