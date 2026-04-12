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


def _candidates_for(hop_hash: str, db: dict) -> list[tuple[str, dict]]:
    """Return [(full_key, entry), ...] for all db nodes matching hop_hash as a prefix."""
    h = hop_hash.lower()
    return [
        (key, entry)
        for key, entry in db.get("nodes", {}).items()
        if key.startswith(h) or h.startswith(key[: len(h)])
    ]


def resolve_path_hops(
    path: list[str],
    db: dict,
    blacklist: list[str] | None = None,
    source_hash: str | None = None,
    observer_id: str | None = None,
) -> list[ResolvedHop]:
    """Resolve a list of hop hashes to ResolvedHop objects (Tier 1 only for now).

    For each hop hash:
    - 0 matches → confidence="unknown", name=hop_hash[:8]
    - 1 match → confidence="unique", fill coords if present
    - N matches (after blacklist filter) → confidence="ambiguous", name="NodeA/NodeB?"

    Blacklist: entries whose name contains any blacklist term (case-insensitive) are
    excluded before counting matches. If blacklist reduces N to 1, that gets "unique".
    """
    bl = [term.lower() for term in (blacklist or [])]

    results: list[ResolvedHop] = []
    for hop_hash in path:
        all_candidates = _candidates_for(hop_hash, db)

        # Apply blacklist filtering
        kept = [
            (key, entry)
            for key, entry in all_candidates
            if not any(
                term in entry.get("name", "").lower() or key.startswith(term)
                for term in bl
            )
        ]

        candidate_keys = [key for key, _ in kept]

        if len(kept) == 0:
            results.append(ResolvedHop(
                raw_hash=hop_hash,
                resolved_key=None,
                name=hop_hash[:8],
                lat=None,
                lon=None,
                confidence="unknown",
                candidates=[],
            ))
        elif len(kept) == 1:
            key, entry = kept[0]
            results.append(ResolvedHop(
                raw_hash=hop_hash,
                resolved_key=key,
                name=entry.get("name", hop_hash[:8]),
                lat=entry.get("lat"),
                lon=entry.get("lon"),
                confidence="unique",
                candidates=candidate_keys,
            ))
        else:
            names = [entry.get("name", key[:8]) for key, entry in kept]
            results.append(ResolvedHop(
                raw_hash=hop_hash,
                resolved_key=None,
                name="/".join(names) + "?",
                lat=None,
                lon=None,
                confidence="ambiguous",
                candidates=candidate_keys,
            ))

    return results
