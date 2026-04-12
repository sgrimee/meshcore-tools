"""Tests for meshcore_tools.disambiguation."""


from meshcore_tools.disambiguation import resolve_path_hops


# Helper: build a 64-char key that starts with a given prefix
def _key(prefix: str) -> str:
    pad = "0" * (64 - len(prefix))
    return prefix + pad


# ---------------------------------------------------------------------------
# Test 1: Tier 1 unique match
# ---------------------------------------------------------------------------

def test_tier1_unique_match():
    """A hop hash that matches exactly one DB node resolves with confidence='unique'."""
    key = _key("aabbccdd")
    db = {"nodes": {key: {"name": "NodeA", "lat": 49.5, "lon": 6.2}}}

    hops = resolve_path_hops(["aabbccdd"], db)

    assert len(hops) == 1
    hop = hops[0]
    assert hop.confidence == "unique"
    assert hop.name == "NodeA"
    assert hop.lat == 49.5
    assert hop.lon == 6.2
    assert hop.resolved_key == key


# ---------------------------------------------------------------------------
# Test 2: Tier 1 no match
# ---------------------------------------------------------------------------

def test_tier1_no_match():
    """A hop hash that matches nothing resolves with confidence='unknown'."""
    db = {"nodes": {}}

    hops = resolve_path_hops(["deadbeef"], db)

    assert len(hops) == 1
    hop = hops[0]
    assert hop.confidence == "unknown"
    assert hop.name == "deadbeef"  # raw hash, first 8 chars
    assert hop.resolved_key is None


# ---------------------------------------------------------------------------
# Test 3: Tier 1 ambiguous, no coords
# ---------------------------------------------------------------------------

def test_tier1_ambiguous_no_coords():
    """Two nodes share the same prefix; no coords anywhere → ambiguous."""
    key_a = _key("aabb1111")
    key_b = _key("aabb2222")
    db = {
        "nodes": {
            key_a: {"name": "NodeA"},
            key_b: {"name": "NodeB"},
        }
    }

    hops = resolve_path_hops(["aabb"], db)

    assert len(hops) == 1
    hop = hops[0]
    assert hop.confidence == "ambiguous"
    assert "NodeA" in hop.name
    assert "NodeB" in hop.name
    assert hop.name.endswith("?")


# ---------------------------------------------------------------------------
# Test 4: Tier 2 by distance — close candidate wins
# ---------------------------------------------------------------------------

def test_tier2_close_candidate_wins():
    """Ambiguous hop: candidate close to observer wins over far candidate."""
    # Observer at origin (0.0, 0.0)
    # Candidate A: ~30 km away (0.27 degrees lat ≈ 30 km)
    # Candidate B: ~1112 km away (10 degrees lon)
    observer_key = _key("obs00000")
    key_a = _key("aabb1111")
    key_b = _key("aabb2222")

    db = {
        "nodes": {
            observer_key: {"name": "Observer", "lat": 0.0, "lon": 0.0},
            key_a: {"name": "NearNode", "lat": 0.27, "lon": 0.0},
            key_b: {"name": "FarNode", "lat": 0.0, "lon": 10.0},
        }
    }

    hops = resolve_path_hops(["aabb"], db, observer_id=observer_key)

    assert len(hops) == 1
    hop = hops[0]
    assert hop.confidence in ("geo_selected", "ambiguous")
    assert hop.name == "NearNode"
    assert hop.resolved_key == key_a


# ---------------------------------------------------------------------------
# Test 5: Tier 2 hard cutoff — >150 km gets inf score, close node wins
# ---------------------------------------------------------------------------

def test_tier2_hard_cutoff_rejects_far_candidate():
    """Candidate beyond 150 km hard cutoff gets inf score; close candidate wins."""
    observer_key = _key("obs00000")
    key_close = _key("aabb1111")
    key_far = _key("aabb2222")

    # Observer at (50.0, 6.0)
    # Close: ~30 km north
    # Far: ~222 km north (2 degrees lat ≈ 222 km, well above 150 km cutoff)
    db = {
        "nodes": {
            observer_key: {"name": "Observer", "lat": 50.0, "lon": 6.0},
            key_close: {"name": "CloseNode", "lat": 50.27, "lon": 6.0},
            key_far: {"name": "FarNode", "lat": 52.0, "lon": 6.0},
        }
    }

    hops = resolve_path_hops(["aabb"], db, observer_id=observer_key)

    assert len(hops) == 1
    hop = hops[0]
    assert hop.name == "CloseNode"
    assert hop.resolved_key == key_close


# ---------------------------------------------------------------------------
# Test 6: Tier 2 falls back gracefully — no coords
# ---------------------------------------------------------------------------

def test_tier2_falls_back_to_ambiguous_without_coords():
    """No coords for candidates or anchors → result stays ambiguous."""
    key_a = _key("aabb1111")
    key_b = _key("aabb2222")
    db = {
        "nodes": {
            key_a: {"name": "NodeA"},
            key_b: {"name": "NodeB"},
        }
    }

    hops = resolve_path_hops(["aabb"], db, source_hash=None, observer_id=None)

    assert len(hops) == 1
    hop = hops[0]
    assert hop.confidence == "ambiguous"


# ---------------------------------------------------------------------------
# Test 7: Blacklist reduces ambiguous to unique
# ---------------------------------------------------------------------------

def test_blacklist_reduces_ambiguous_to_unique():
    """Blacklisting one of two candidates leaves a unique match."""
    key_a = _key("aabb1111")
    key_b = _key("aabb2222")
    db = {
        "nodes": {
            key_a: {"name": "GoodNode", "lat": 49.5, "lon": 6.0},
            key_b: {"name": "BadNode"},
        }
    }

    hops = resolve_path_hops(["aabb"], db, blacklist=["bad"])

    assert len(hops) == 1
    hop = hops[0]
    assert hop.confidence == "unique"
    assert hop.name == "GoodNode"
    assert hop.resolved_key == key_a


# ---------------------------------------------------------------------------
# Test 8: Combinatorial path — two consecutive ambiguous hops
# ---------------------------------------------------------------------------

def test_combinatorial_path_two_ambiguous_hops():
    """Two consecutive ambiguous hops; geographically consistent pair wins."""
    # hop1 candidates: A1 near (50.0, 6.0), A2 far at (0.0, 0.0)
    # hop2 candidates: B1 near (50.1, 6.1), B2 far at (0.1, 0.1)
    # Observer near (50.2, 6.2)
    # A1→B1 path is consistent; A2→B2 path is far from observer
    observer_key = _key("obs00000")
    key_a1 = _key("aaaa1111")
    key_a2 = _key("aaaa2222")
    key_b1 = _key("bbbb1111")
    key_b2 = _key("bbbb2222")

    db = {
        "nodes": {
            observer_key: {"name": "Observer", "lat": 50.2, "lon": 6.2},
            key_a1: {"name": "A1", "lat": 50.0, "lon": 6.0},
            key_a2: {"name": "A2", "lat": 0.0, "lon": 0.0},
            key_b1: {"name": "B1", "lat": 50.1, "lon": 6.1},
            key_b2: {"name": "B2", "lat": 0.1, "lon": 0.1},
        }
    }

    hops = resolve_path_hops(["aaaa", "bbbb"], db, observer_id=observer_key)

    assert len(hops) == 2
    hop1, hop2 = hops

    assert hop1.name == "A1"
    assert hop1.resolved_key == key_a1
    assert hop2.name == "B1"
    assert hop2.resolved_key == key_b1
