from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from observability.anomaly import zscore_detector


def approximate_token_lengths(texts: Iterable[str]) -> list[int]:
    # Deliberately simple proxy; no tokenizer/model download needed.
    return [len(str(t).split()) for t in texts]


def detect_text_length_shift(
    current_texts: Iterable[str],
    baseline_batch_means: Iterable[float],
    *,
    threshold: float = 3.0,
) -> dict[str, Any]:
    lengths = approximate_token_lengths(current_texts)
    current_mean = float(np.mean(lengths)) if lengths else 0.0
    result = zscore_detector(current_mean, baseline_batch_means, threshold=threshold)
    result["metric"] = "mean_text_length"
    result["current_mean"] = current_mean
    return result


def detect_embedding_norm_shift(
    current_norms: Iterable[float], baseline_norms: Iterable[float]
) -> dict[str, Any]:
    """Embedding-space drift proxy using precomputed vector norms.

    No embedding model is required: a shift in the mean/spread of embedding
    norms (e.g. after a re-indexing bug, truncated content, or an embedding
    model swap) is a cheap signal that the retrieval space moved, checked
    with the same zscore baseline used for other scalar metrics.
    """
    current = list(current_norms)
    baseline = list(baseline_norms)
    if not current or not baseline:
        return {"is_anomaly": False, "score": 0.0, "method": "embedding_norm_zscore", "reason": "empty_input"}
    current_mean = float(np.mean(current))
    result = zscore_detector(current_mean, baseline)
    result["method"] = "embedding_norm_zscore"
    result["current_mean_norm"] = current_mean
    return result
