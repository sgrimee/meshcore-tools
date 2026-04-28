"""Disambiguation of repeater node hashes in packet paths."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Literal

from meshcore_tools.db import candidates_for

UNKNOWN_COORD_PENALTY = 10.0
GEO_CONFIDENCE_THRESHOLD = 0.5
_MAX_COMBOS = 1000
_LORA_HARD_CUTOFF_KM = 150.0


@dataclass
class ResolvedHop:
    raw_hash: str                # original hex string from packet path (1–4 bytes)
    resolved_key: str | None     # matched 64-char key, or None
    name: str                    # display name: node name, "NodeA/NodeB?", or raw 8-char prefix
    lat: float | None
    lon: float | None
    confidence: Literal["unique", "geo_selected", "ambiguous", "unknown"]
    candidates: list[str] = field(default_factory=list)  # all candidate 64-char keys


def resolve_path_hops(
    path: list[str],
    db: dict,
    blacklist: list[str] | None = None,
    source_hash: str | None = None,
    observer_id: str | None = None,
) -> list[ResolvedHop]:
    """Resolve a list of hop hashes to ResolvedHop objects (Tier 1 + Tier 2).

    For each hop hash:
    - 0 matches → confidence="unknown", name=hop_hash[:8]
    - 1 match → confidence="unique", fill coords if present
    - N matches (after blacklist filter) → confidence="ambiguous", name="NodeA/NodeB?"

    Blacklist: entries whose name contains any blacklist term (case-insensitive) are
    excluded before counting matches. If blacklist reduces N to 1, that gets "unique".

    After Tier 1, if any hops remain ambiguous, Tier 2 geographic scoring is applied
    using source/observer coordinates as anchors when available.
    """
    bl = [term.lower() for term in (blacklist or [])]

    results: list[ResolvedHop] = []
    for hop_hash in path:
        all_candidates = candidates_for(hop_hash, db)

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

    # Tier 2: geographic scoring for ambiguous hops
    if any(hop.confidence == "ambiguous" for hop in results):
        spatial_index = _build_spatial_index(db)
        source_coords = spatial_index.get(source_hash.lower()) if source_hash else None
        observer_coords = spatial_index.get(observer_id.lower()) if observer_id else None
        results = _resolve_ambiguous_hops_by_geometry(
            results, spatial_index, source_coords, observer_coords, db
        )

    return results


def _build_spatial_index(db: dict) -> dict[str, tuple[float, float]]:
    """Return {full_key: (lat, lon)} for all nodes with coordinates."""
    index: dict[str, tuple[float, float]] = {}
    for key, entry in db.get("nodes", {}).items():
        lat = entry.get("lat")
        lon = entry.get("lon")
        if lat is not None and lon is not None:
            index[key] = (float(lat), float(lon))
    return index


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in km using the Haversine formula."""
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _score_transition(
    coord_a: tuple[float, float] | None,
    coord_b: tuple[float, float] | None,
) -> float:
    """Score the transition cost between two consecutive hops.

    Returns:
    - UNKNOWN_COORD_PENALTY if either coord is None
    - math.inf if distance > _LORA_HARD_CUTOFF_KM (physically impossible for LoRa)
    - sigmoid decay: 1 / (1 + exp(-(d - 50) / 20)) otherwise
      near-0 cost below ~30 km, 0.5 at 50 km, near-1.0 above ~80 km
    """
    if coord_a is None or coord_b is None:
        return UNKNOWN_COORD_PENALTY
    d = _haversine_km(coord_a[0], coord_a[1], coord_b[0], coord_b[1])
    if d > _LORA_HARD_CUTOFF_KM:
        return math.inf
    return 1.0 / (1.0 + math.exp(-(d - 50.0) / 20.0))


def _score_candidate_sequence(
    sequence: list[str],
    spatial_index: dict[str, tuple[float, float]],
    source_coords: tuple[float, float] | None,
    observer_coords: tuple[float, float] | None,
) -> float:
    """Score a full candidate sequence by summing transition costs.

    Builds the chain: source → seq[0] → seq[1] → ... → seq[-1] → observer
    (anchors are only included when not None).
    Each adjacent pair contributes _score_transition(coords_a, coords_b).
    """
    coords: list[tuple[float, float] | None] = []
    if source_coords is not None:
        coords.append(source_coords)
    for key in sequence:
        coords.append(spatial_index.get(key))
    if observer_coords is not None:
        coords.append(observer_coords)

    return sum(
        _score_transition(coords[i], coords[i + 1]) for i in range(len(coords) - 1)
    )


def _resolve_ambiguous_hops_per_hop(
    hops: list[ResolvedHop],
    spatial_index: dict[str, tuple[float, float]],
    source_coords: tuple[float, float] | None,
    observer_coords: tuple[float, float] | None,
    db: dict,
) -> list[ResolvedHop]:
    """Per-hop proximity fallback for paths where combination count exceeds _MAX_COMBOS.

    Iteratively resolves ambiguous hops: if exactly one candidate is within
    _LORA_HARD_CUTOFF_KM of any known anchor, assign confidence="geo_selected".
    Newly resolved hops become anchors for subsequent iterations (chain propagation).
    Terminates when no new hops can be resolved.
    """
    anchors: list[tuple[float, float]] = []
    if source_coords is not None:
        anchors.append(source_coords)
    if observer_coords is not None:
        anchors.append(observer_coords)
    for hop in hops:
        if hop.confidence in ("unique", "geo_selected") and hop.lat is not None and hop.lon is not None:
            anchors.append((hop.lat, hop.lon))

    updated = list(hops)
    for _ in range(len(hops)):
        made_progress = False
        for i, hop in enumerate(updated):
            if hop.confidence != "ambiguous" or not anchors:
                continue
            plausible: list[tuple[str, tuple[float, float]]] = []
            for key in hop.candidates:
                coords = spatial_index.get(key)
                if coords is None:
                    continue
                if any(
                    _haversine_km(coords[0], coords[1], a[0], a[1]) <= _LORA_HARD_CUTOFF_KM
                    for a in anchors
                ):
                    plausible.append((key, coords))
            if len(plausible) == 1:
                chosen_key, coords = plausible[0]
                entry = db.get("nodes", {}).get(chosen_key, {})
                updated[i] = ResolvedHop(
                    raw_hash=hop.raw_hash,
                    resolved_key=chosen_key,
                    name=entry.get("name", chosen_key[:8]),
                    lat=coords[0],
                    lon=coords[1],
                    confidence="geo_selected",
                    candidates=hop.candidates,
                )
                anchors.append(coords)
                made_progress = True
        if not made_progress:
            break

    return updated


def _resolve_ambiguous_hops_by_geometry(
    hops: list[ResolvedHop],
    spatial_index: dict[str, tuple[float, float]],
    source_coords: tuple[float, float] | None,
    observer_coords: tuple[float, float] | None,
    db: dict,
) -> list[ResolvedHop]:
    """Try to resolve ambiguous hops using geographic scoring.

    Algorithm:
    1. If total candidate combinations > _MAX_COMBOS: return hops unchanged
    2. If no candidate has coordinates AND no anchor coords: return unchanged
    3. Enumerate all combinations (ambiguous hops vary, unique hops are fixed)
    4. Score each combination with _score_candidate_sequence
    5. Pick the winning combination (lowest score)
    6. If winning score is +inf, use lowest finite score instead (if any)
    7. Apply winning combination:
       - confidence="geo_selected" if score delta vs runner-up > GEO_CONFIDENCE_THRESHOLD
       - confidence="ambiguous" otherwise (best guess but not confident)
    8. Return the updated hops list (non-ambiguous hops are returned unchanged)
    """
    # Step 1: check combo count
    combo_count = 1
    for hop in hops:
        combo_count *= len(hop.candidates) if hop.candidates else 1
    if combo_count > _MAX_COMBOS:
        return _resolve_ambiguous_hops_per_hop(
            hops, spatial_index, source_coords, observer_coords, db
        )

    # Step 2: check if any useful coords exist
    all_candidate_keys = [key for hop in hops for key in hop.candidates]
    has_any_coords = (
        any(key in spatial_index for key in all_candidate_keys)
        or source_coords is not None
        or observer_coords is not None
    )
    if not has_any_coords:
        return hops

    # Step 3 & 4: enumerate and score all combinations
    candidate_lists = [hop.candidates if hop.candidates else [] for hop in hops]
    scored: list[tuple[float, tuple[str, ...]]] = []
    for combo in itertools.product(*candidate_lists):
        score = _score_candidate_sequence(list(combo), spatial_index, source_coords, observer_coords)
        scored.append((score, combo))

    if not scored:
        return hops

    # Step 5 & 6: pick winner (lowest score, prefer finite)
    scored.sort(key=lambda x: (math.isinf(x[0]), x[0]))
    best_score, best_combo = scored[0]

    # Determine runner-up score for confidence threshold
    runner_up_score = scored[1][0] if len(scored) > 1 else best_score

    # Step 7: apply winning combination
    # Confident if: best is finite AND (runner-up is physically impossible OR delta > threshold)
    confident = not math.isinf(best_score) and (
        math.isinf(runner_up_score)
        or (runner_up_score - best_score) > GEO_CONFIDENCE_THRESHOLD
    )
    new_confidence: Literal["geo_selected", "ambiguous"] = (
        "geo_selected" if confident else "ambiguous"
    )

    updated: list[ResolvedHop] = []
    for hop, chosen_key in zip(hops, best_combo):
        if hop.confidence == "ambiguous":
            coords = spatial_index.get(chosen_key)
            entry = db.get("nodes", {}).get(chosen_key, {})
            # Preserve the composite "A/B?" name when not confident — single name
            # would imply resolution that hasn't happened.  Only narrow to a
            # single name when we are actually committing to geo_selected.
            name = (
                entry.get("name", chosen_key[:8])
                if new_confidence == "geo_selected"
                else hop.name
            )
            updated.append(ResolvedHop(
                raw_hash=hop.raw_hash,
                resolved_key=chosen_key,
                name=name,
                lat=coords[0] if coords else None,
                lon=coords[1] if coords else None,
                confidence=new_confidence,
                candidates=hop.candidates,
            ))
        else:
            updated.append(hop)

    return updated
