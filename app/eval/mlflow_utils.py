from __future__ import annotations

from contextlib import contextmanager
from typing import Dict, Optional

import mlflow


MLFLOW_EXPERIMENT_NAME = "unreserved_rag_eval"


def init_mlflow(tracking_uri: Optional[str] = None, experiment_name: Optional[str] = None) -> None:
    """
    Initialise MLflow tracking.

    - tracking_uri: e.g. "file:/tmp/mlruns" or http(s) URI to a tracking server.
    - experiment_name: override default experiment name if desired.
    """
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)

    mlflow.set_experiment(experiment_name or MLFLOW_EXPERIMENT_NAME)


@contextmanager
def start_eval_run(run_name: str, tags: Optional[Dict[str, str]] = None):
    """
    Context manager that wraps mlflow.start_run with sensible defaults.
    """
    with mlflow.start_run(run_name=run_name):
        if tags:
            mlflow.set_tags(tags)
        yield

