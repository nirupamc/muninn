"""Vector serialization and similarity helpers."""

from __future__ import annotations

import numpy as np


def serialize_vector(vector: list[float] | np.ndarray) -> bytes:
    """Serialize a float vector to a float32 BLOB."""
    arr = np.asarray(vector, dtype=np.float32)
    if arr.ndim != 1:
        raise ValueError("embedding vector must be 1-dimensional")
    return arr.tobytes()


def deserialize_vector(blob: bytes) -> np.ndarray:
    """Deserialize a float32 BLOB into a 1-D NumPy array."""
    return np.frombuffer(blob, dtype=np.float32).copy()


def l2_normalize(vector: np.ndarray) -> np.ndarray:
    """Return an L2-normalized copy of the vector."""
    arr = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm == 0.0:
        return arr
    return arr / norm


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Cosine similarity between two vectors.

    If both inputs are already L2-normalized, this equals the dot product.
    """
    left = np.asarray(a, dtype=np.float32)
    right = np.asarray(b, dtype=np.float32)
    if left.shape != right.shape:
        raise ValueError(
            f"vector dimension mismatch: {left.shape[0]} vs {right.shape[0]}"
        )
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))
