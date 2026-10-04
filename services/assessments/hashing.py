"""Hashes that decide whether an assessment is reused, shown, or asked for again."""
import hashlib
import json
from typing import Any


def canonical(payload: Any) -> str:
    """One spelling per value: sorted keys, no whitespace, so equal inputs hash equal."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(payload: Any) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()
