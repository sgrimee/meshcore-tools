"""Disambiguation of repeater node hashes in packet paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ResolvedHop:
    raw_hash: str                # original hex string from packet path (1–4 bytes)
    resolved_key: str | None     # matched 64-char key, or None
    name: str                    # display name: node name, "NodeA/NodeB?", or raw 8-char prefix
    lat: float | None
    lon: float | None
    confidence: Literal["unique", "geo_selected", "ambiguous", "unknown"]
    candidates: list[str] = field(default_factory=list)  # all candidate 64-char keys
