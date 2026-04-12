# Plan: Disambiguate Repeater Nodes on Collisions (Issue #33)

## Problem & Current State

Packet paths contain 1–4 byte hashes representing repeater hops (typically 1 byte). With only 256
usable values, collisions are guaranteed in any non-trivial mesh — ~54% of 1-byte prefixes collide
in a ~384-node database.

The current blacklist approach requires manual user configuration per collision and gives no
confidence signal. It is unreliable because:
- Users must discover collisions themselves
- Blacklisting one node hides it everywhere, not just for the colliding hop
- New nodes added to the DB can introduce silent new collisions

The solution is a **two-tier automatic disambiguation** system. Tiers 3 & 4 from the research
document are deferred (see below).

---

## Architecture Decision: New `disambiguation.py` Module

All resolution logic goes in a new `src/meshcore_tools/disambiguation.py`. This:
- Keeps `db.py` as pure DB operations
- Avoids spatial math contaminating UI files (`monitor.py`, `map_view.py`)
- Makes the core logic independently testable before touching UI

The blacklist is retained as a user escape hatch but is no longer the primary mechanism.

---

## Step 1 — `ResolvedHop` data model (`disambiguation.py`)

Define a dataclass representing one resolved hop:

```python
@dataclass
class ResolvedHop:
    raw_hash: str                # original hex string from packet path (1–4 bytes)
    resolved_key: str | None     # matched 64-char key, or None
    name: str                    # display name: node name, "NodeA/NodeB?", or raw 8-char prefix
    lat: float | None
    lon: float | None
    confidence: Literal["unique", "geo_selected", "ambiguous", "unknown"]
    candidates: list[str]        # all candidate 64-char keys (for logging/debug)
```

`confidence` values:
- `"unique"` — Tier 1 found exactly one match
- `"geo_selected"` — geographic scoring picked one winner from multiple candidates
- `"ambiguous"` — multiple candidates but insufficient geometry to choose
- `"unknown"` — no DB match at all

**Dependencies:** none  
**Complexity:** Low

---

## Step 2 — Tier 1: Direct prefix lookup (`resolve_path_hops()`)

Implement the main entry point:

```python
def resolve_path_hops(
    path: list[str],
    db: dict,
    blacklist: list[str] | None = None,
    source_hash: str | None = None,
    observer_id: str | None = None,
) -> list[ResolvedHop]:
```

For each hop hash:
- 0 matches → `confidence="unknown"`, `name=hop_hash[:8]`
- 1 match → `confidence="unique"`, fill coords if present
- N matches → collect candidates, escalate to Tier 2

Internal helper: `_candidates_for(hash, db) -> list[tuple[str, dict]]` returns
`[(full_key, entry), ...]`. Blacklist is applied here before escalation — if blacklisting reduces
N candidates to 1, that becomes `confidence="unique"`.

**Dependencies:** Step 1  
**Complexity:** Low — consolidates logic already spread across `db.py` and `map_view.py`

---

## Step 3 — Spatial helpers (`disambiguation.py`)

```python
def _build_spatial_index(db: dict) -> dict[str, tuple[float, float]]:
    """Return {full_key: (lat, lon)} for all nodes with coordinates."""

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Pure-Python Haversine distance in km."""
```

Built once per `resolve_path_hops()` call, not cached. Rationale: the DB dict is mutated by
`learn_from_advert()`; a stale spatial index would silently give wrong results. Per-call
construction is correct by default and costs microseconds for ~400 nodes.

No numpy/scipy — pure Python avoids heavy dependencies in the base install and is accurate enough
for geographic disambiguation at LoRa scales.

**Dependencies:** none  
**Complexity:** Low

---

## Step 4 — Tier 2: Geographic scoring (`disambiguation.py`)

### Why not full HMM Viterbi

Paths have 1–3 hops with 2–5 candidates each → max ~125 combinations. Exhaustive enumeration is
correct and avoids implementing log-domain arithmetic or adding scipy. Full Viterbi would be
equivalent for this scale.

### Scoring a transition between consecutive hops

```python
def _score_transition(
    coord_a: tuple[float, float] | None,
    coord_b: tuple[float, float] | None,
) -> float:
```

- Either coord is None → `UNKNOWN_COORD_PENALTY = 10.0`
- Distance > 150 km → `+inf` (hard LoRa physical cutoff)
- Otherwise: sigmoid decay centered on 50 km: `1 / (1 + exp(-(d - 50) / 20))`
  - Near-0 cost below 30 km, 0.5 at 50 km, near-1.0 above 80 km

### Full sequence scorer

```python
def _score_candidate_sequence(
    sequence: list[tuple[str, dict]],    # [(key, entry), ...] one candidate per hop
    spatial_index: dict[str, tuple[float, float]],
    source_coords: tuple[float, float] | None,
    observer_coords: tuple[float, float] | None,
) -> float:
```

Scores the full path by summing transition costs, anchoring against source/observer where available.

### Resolver

```python
def _resolve_ambiguous_hops_by_geometry(
    hops: list[ResolvedHop],
    spatial_index: dict[str, tuple[float, float]],
    source_coords: tuple[float, float] | None,
    observer_coords: tuple[float, float] | None,
) -> list[ResolvedHop]:
```

1. If total candidate combinations > 1,000: skip (return as-is, future-proofing guard)
2. If no candidate has coordinates and no anchor: return as-is
3. Enumerate all combinations for ambiguous hops (unique hops are fixed)
4. Score each combination
5. If min score is `+inf`: use lowest finite score if any, else leave ambiguous
6. Apply winning combination:
   - `confidence="geo_selected"` if cost delta between winner and runner-up > `GEO_CONFIDENCE_THRESHOLD = 0.5`
   - Otherwise `confidence="ambiguous"` (winner is best guess but not confident)

**Dependencies:** Steps 2–3  
**Complexity:** Medium — sigmoid scoring and combinatorial enumeration

---

## Step 5 — Wire Tier 2 into `resolve_path_hops()`

Extend the function from Step 2:
1. After Tier 1 resolves all hops, check if any are ambiguous
2. If yes, AND geometry is available: call `_resolve_ambiguous_hops_by_geometry()`
3. Source and observer coordinates looked up from `spatial_index` via their hashes

**Dependencies:** Steps 2–4  
**Complexity:** Low

---

## Step 6 — Update `monitor.py:format_path()` (lines 37–106)

Add optional parameter:

```python
def format_path(
    ...,
    resolved_hops: list[ResolvedHop] | None = None,
) -> str:
```

When `resolved_hops` is provided, use `hop.name` directly instead of calling
`resolve_name_filtered()` per hop. Existing callers without the new parameter are unaffected.

Compute `resolved_hops` once in `_add_packet_row()` (line 846) and pass to `format_path()`.

**Dependencies:** Steps 1–5  
**Complexity:** Low-medium

---

## Step 7 — Update `map_view.py:collect_map_nodes()` (lines 63–153)

Add optional parameter:

```python
def collect_map_nodes(
    packet: dict,
    db: dict,
    blacklist: list[str] | None = None,
    resolved_hops: list[ResolvedHop] | None = None,
) -> tuple[...]:
```

When provided, use `hop.lat`/`hop.lon`/`hop.name` instead of calling `_lookup_coords()` per relay.
Source, observer, and destination still use `_lookup_coords()` directly (they are not relay hops).

Call `resolve_path_hops()` in `load_packet()` and `_refresh_map()` in the **UI thread** — not
inside the tile-fetch worker thread, which is not DB-safe.

**Dependencies:** Steps 1–5  
**Complexity:** Medium — threading boundary requires care

---

## Step 8 — Confidence indicators in detail panel (`monitor.py:_path_detail_lines()`, lines 141–181)

Update hop display in the packet detail panel:
- `"geo_selected"` → node name + `[dim](geo)[/dim]`
- `"ambiguous"` → `NodeA/NodeB?` + `[dim](ambiguous)[/dim]`
- `"unknown"` → raw prefix as before
- `"unique"` → node name, no suffix (clean common case)

**Dependencies:** Steps 1–5  
**Complexity:** Low

---

## Step 9 — Tests for `disambiguation.py` (`tests/test_disambiguation.py`)

Follow existing style in `test_db.py`: plain dicts, no fixtures.

Test cases:
1. Tier 1 unique match → `confidence="unique"`, correct name and coords
2. Tier 1 no match → `confidence="unknown"`, name is raw 8-char prefix
3. Tier 1 ambiguous, no coords anywhere → `confidence="ambiguous"`, both names in display string
4. Tier 2 by distance — two candidates, one far (200 km from observer), one close (30 km) → far excluded
5. Tier 2 hard cutoff — candidate >150 km from any plausible anchor gets `+inf`, excluded
6. Tier 2 falls back gracefully — no coordinate anchor → returns `confidence="ambiguous"`
7. Blacklist reduces ambiguous to unique — one candidate blacklisted, remaining gets `"unique"`
8. Combinatorial path — two consecutive ambiguous hops resolved together by geographic scoring

**Dependencies:** Steps 1–5  
**Complexity:** Medium — needs representative DB fixtures with coords

---

## Step 10 — Update existing tests

Files: `tests/test_monitor_tab.py`, `tests/test_map_view.py`

Existing tests pass unchanged (new parameters default to `None`). Add one new test per file:
- `test_monitor_tab.py`: `format_path()` uses `hop.name` from `resolved_hops` when provided
- `test_map_view.py`: `collect_map_nodes()` uses `hop.lat`/`hop.lon` from `resolved_hops` when provided, not `_lookup_coords()`

**Dependencies:** Steps 6–7  
**Complexity:** Low

---

## Dependency Order

```
Step 1 (ResolvedHop dataclass)
  └─ Step 2 (Tier 1 resolve_path_hops)
       ├─ Step 3 (spatial helpers: index + haversine)
       │    └─ Step 4 (Tier 2 geographic scoring)
       │         └─ Step 5 (wire Tier 2 into resolve_path_hops)
       │              ├─ Step 6 (format_path in monitor.py)
       │              │    └─ Step 8 (detail panel confidence indicators)
       │              ├─ Step 7 (collect_map_nodes in map_view.py)
       │              └─ Step 9 (disambiguation tests)
       └─ Step 10 (update existing tests)
```

Steps 1–5 are pure library, fully testable before touching any UI code.
Steps 6, 7, 8 are parallel UI wiring once Step 5 is done.

---

## Tiers 3 & 4 — Out of Scope

| Tier | Reason deferred |
|------|-----------------|
| **Tier 3** (cross-observer consensus) | Requires per-observer path extraction + RSSI/SNR weighting; significant data model changes. Good follow-up issue once Tiers 1+2 are stable. |
| **Tier 4** (ghost node DBSCAN) | Needs corpus-level analysis across many packets, external scikit-learn dependency, separate storage for inferred nodes, new UI. Separate issue. |

---

## Key Trade-offs

1. **The close-collision case.** Two nodes sharing a 1-byte prefix and located only ~15 km apart
   cannot be disambiguated by geography — both are plausible LoRa relays. These remain
   `confidence="ambiguous"`. The blacklist is the only override for pathological cases like this.

2. **No numpy/scipy.** Pure Python sigmoid and Haversine are sufficient for LoRa-scale distances.
   Avoids adding heavy dependencies to the base install.

3. **No spatial index caching.** Per-call construction is correct by default. Re-evaluate only if
   profiling shows it matters (it won't for ~400 nodes).

4. **`source_hash` and `observer_id` improve Tier 2 accuracy** but are optional — all call sites
   have this data available in the `packet` dict and should pass it. The function degrades
   gracefully when absent (scores only intermediate transitions).

5. **Exhaustive enumeration guard at 1,000 combinations.** With typical 1–3 hops and 2–5
   candidates, max is ~125. The guard prevents pathological slowdowns if DB grows large.

---

## Critical Files

| File | Role |
|------|------|
| `src/meshcore_tools/disambiguation.py` | **New** — all Tier 1 + Tier 2 logic |
| `src/meshcore_tools/db.py` | Reference for `_resolved_names` pattern to replicate in disambiguation.py |
| `src/meshcore_tools/monitor.py` | Consumer — `format_path()` line 37, `_path_detail_lines()` line 141, `_add_packet_row()` line 846 |
| `src/meshcore_tools/map_view.py` | Consumer — `collect_map_nodes()` line 63, `MapSidePanel.load_packet()` ~line 366, `PacketMapScreen._refresh_map()` ~line 500 |
| `tests/test_disambiguation.py` | **New** — all disambiguation unit tests |
| `tests/test_monitor_tab.py` | Update — add resolved_hops test |
| `tests/test_map_view.py` | Update — add resolved_hops test |
