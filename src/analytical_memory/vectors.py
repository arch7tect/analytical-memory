from __future__ import annotations

import math
import struct
import unicodedata
from collections.abc import Sequence


def preprocess_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n")
    normalized = normalized.replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("embedding input must not be empty")
    return normalized


def encode_vector(values: Sequence[float], dimensions: int) -> bytes:
    if len(values) != dimensions:
        raise ValueError("embedding dimensions do not match the profile")
    finite = [float(value) for value in values]
    if not all(math.isfinite(value) for value in finite):
        raise ValueError("embedding contains a non-finite value")
    rounded = struct.unpack(f"<{dimensions}f", struct.pack(f"<{dimensions}f", *finite))
    norm = math.sqrt(math.fsum(value * value for value in rounded))
    if norm == 0.0:
        raise ValueError("embedding has zero norm")
    normalized = [value / norm for value in rounded]
    return struct.pack(f"<{dimensions}f", *normalized)


def decode_vector(value: bytes, dimensions: int) -> tuple[float, ...]:
    if len(value) != dimensions * 4:
        raise ValueError("stored embedding byte size does not match its dimensions")
    return struct.unpack(f"<{dimensions}f", value)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("cannot compare embeddings with different dimensions")
    left_norm = math.sqrt(math.fsum(value * value for value in left))
    right_norm = math.sqrt(math.fsum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("cannot compare a zero-norm embedding")
    return math.fsum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )
