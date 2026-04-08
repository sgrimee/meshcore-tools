"""Tests for lma.db."""

import json
from unittest.mock import patch


from meshcore_tools.db import (
    is_blacklisted,
    is_input_node,
    learn_from_advert,
    load_db,
    parse_input_file,
    resolve_name,
    resolve_name_filtered,
    save_db,
    update,
)


class _StubCoordProvider:
    def fetch_node_coords(self): return {}


INPUT_CONTENT = """\
sg-t1000-2                       CLI   6766f573d2ec  Flood
1→Nils-echo                      CLI   5ab07f54cd13  Flood
gw-charly                        CLI   7d1e1ad2a470c8f3a1b2c3d4e5f60708090a0b0c0d0e0f101112131415161718
bad-line
short
"""


def test_parse_input_file_basic(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text(INPUT_CONTENT)
    nodes = parse_input_file(f)
    assert "6766f573d2ec" in nodes
    assert nodes["6766f573d2ec"]["name"] == "sg-t1000-2"
    assert nodes["6766f573d2ec"]["type"] == "CLI"
    assert nodes["6766f573d2ec"]["routing"] == "Flood"
    assert nodes["6766f573d2ec"]["key_complete"] is False


def test_parse_input_file_strips_line_number(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text(INPUT_CONTENT)
    nodes = parse_input_file(f)
    assert "5ab07f54cd13" in nodes
    assert nodes["5ab07f54cd13"]["name"] == "Nils-echo"


def test_parse_input_file_full_key(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text(INPUT_CONTENT)
    nodes = parse_input_file(f)
    full_key = "7d1e1ad2a470c8f3a1b2c3d4e5f60708090a0b0c0d0e0f101112131415161718"
    assert nodes[full_key]["key_complete"] is True


def test_parse_input_file_source_is_filename(tmp_path):
    f = tmp_path / "sam.txt"
    f.write_text("mynode CLI aabbccdd Flood\n")
    nodes = parse_input_file(f)
    assert nodes["aabbccdd"]["source"] == "sam.txt"


def test_load_db_missing_file(tmp_path):
    with patch("meshcore_tools.db.DB_FILE", tmp_path / "nodes.json"):
        db = load_db()
    assert db == {"nodes": {}}


def test_load_db_reads_existing(tmp_path):
    db_file = tmp_path / "nodes.json"
    db_file.write_text(json.dumps({"nodes": {"aabb": {"name": "x"}}}))
    with patch("meshcore_tools.db.DB_FILE", db_file):
        db = load_db()
    assert db["nodes"]["aabb"]["name"] == "x"


def test_save_db_roundtrip(tmp_path):
    db_file = tmp_path / "nodes.json"
    db = {"nodes": {"aabb": {"name": "y", "type": "CLI"}}}
    with patch("meshcore_tools.db.DB_FILE", db_file):
        save_db(db)
        loaded = load_db()
    assert loaded == db


def test_update_merge_partial_key(tmp_path):
    """Partial key from input file gets replaced by full key from API, preserving type/routing."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "test.txt").write_text("my-node REP aabbccdd Flood\n")

    full_key = "aabbccdd" + "0" * 56
    api_nodes = {full_key: {"name": "api-name", "type": "CLI", "source": "api:LUX", "key_complete": True, "last_seen": "2026-01-01"}}

    db_file = tmp_path / "nodes.json"

    class _StubNodeProvider:
        def fetch_nodes(self, region): return api_nodes

    with patch("meshcore_tools.db.INPUT_DIR", input_dir), \
         patch("meshcore_tools.db.DB_FILE", db_file):
        update("LUX", node_provider=_StubNodeProvider(), coord_provider=_StubCoordProvider())

    db = json.loads(db_file.read_text())
    assert full_key in db["nodes"]
    assert "aabbccdd" not in db["nodes"]
    # type and routing from input file preserved
    assert db["nodes"][full_key]["type"] == "REP"
    assert db["nodes"][full_key]["routing"] == "Flood"
    # last_seen from API preserved
    assert db["nodes"][full_key]["last_seen"] == "2026-01-01"


def test_update_api_failure_continues(tmp_path):
    """API failure is non-fatal; input file nodes still saved."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "test.txt").write_text("my-node CLI aabbccdd\n")
    db_file = tmp_path / "nodes.json"

    class _StubNodeProvider:
        def fetch_nodes(self, region): raise Exception("network error")

    with patch("meshcore_tools.db.INPUT_DIR", input_dir), \
         patch("meshcore_tools.db.DB_FILE", db_file):
        update("LUX", node_provider=_StubNodeProvider(), coord_provider=_StubCoordProvider())

    db = json.loads(db_file.read_text())
    assert "aabbccdd" in db["nodes"]


# --- resolve_name ---

def test_resolve_name_exact():
    db = {"nodes": {"aabbccdd": {"name": "my-node"}}}
    assert resolve_name("aabbccdd", db) == "my-node"


def test_resolve_name_prefix():
    db = {"nodes": {"aabbccdd11223344": {"name": "my-node"}}}
    assert resolve_name("aabbccdd", db) == "my-node"


def test_resolve_name_not_found():
    db = {"nodes": {"aabbccdd": {"name": "my-node"}}}
    assert resolve_name("deadbeef", db) == "deadbeef"


def test_resolve_name_ambiguous():
    db = {"nodes": {"aabb1111": {"name": "node-a"}, "aabb2222": {"name": "node-b"}}}
    result = resolve_name("aabb", db)
    assert result.endswith("?")
    assert "node-a" in result
    assert "node-b" in result


# --- learn_from_advert ---

def test_learn_from_advert_new_node():
    db = {"nodes": {}}
    key = "a" * 64
    changed = learn_from_advert(db, key, "my-node", "ChatNode")
    assert changed is True
    assert db["nodes"][key]["name"] == "my-node"
    assert db["nodes"][key]["type"] == "CLI"
    assert db["nodes"][key]["source"] == "advert"
    assert db["nodes"][key]["key_complete"] is True


def test_learn_from_advert_with_coords():
    db = {"nodes": {}}
    key = "b" * 64
    changed = learn_from_advert(db, key, "gw", "Repeater", lat=49.5, lon=6.2)
    assert changed is True
    assert db["nodes"][key]["lat"] == 49.5
    assert db["nodes"][key]["lon"] == 6.2


def test_learn_from_advert_no_change():
    db = {"nodes": {}}
    key = "c" * 64
    learn_from_advert(db, key, "gw", "ChatNode", lat=1.0, lon=2.0)
    changed = learn_from_advert(db, key, "gw", "ChatNode", lat=1.0, lon=2.0)
    assert changed is False


def test_learn_from_advert_skips_handcurated():
    db = {"nodes": {}}
    key = "d" * 64
    db["nodes"][key] = {"name": "curated", "type": "REP", "source": "nodes.txt"}
    changed = learn_from_advert(db, key, "new-name", "ChatNode")
    assert changed is False
    assert db["nodes"][key]["name"] == "curated"


def test_learn_from_advert_invalid_key():
    db = {"nodes": {}}
    changed = learn_from_advert(db, "tooshort", "x", "ChatNode")
    assert changed is False
    assert db["nodes"] == {}


def test_learn_from_advert_zero_coords_omitted():
    """lat=0, lon=0 should not be stored (treated as no location)."""
    db = {"nodes": {}}
    key = "e" * 64
    learn_from_advert(db, key, "gw", "ChatNode", lat=0.0, lon=0.0)
    assert "lat" not in db["nodes"][key]
    assert "lon" not in db["nodes"][key]


def test_learn_from_advert_updates_existing_api_node():
    """Existing api:-sourced node gets updated when data changes."""
    db = {"nodes": {}}
    key = "f" * 64
    db["nodes"][key] = {"name": "old-name", "type": "CLI", "source": "api:LUX"}
    changed = learn_from_advert(db, key, "new-name", "ChatNode")
    assert changed is True
    assert db["nodes"][key]["name"] == "new-name"


# ---------------------------------------------------------------------------
# parse_input_file edge cases
# ---------------------------------------------------------------------------

def test_parse_input_file_invalid_hex_key_skipped(tmp_path):
    """Lines with non-hex characters in the key field are skipped."""
    f = tmp_path / "test.txt"
    f.write_text("bad-node CLI notahex Flood\n")
    nodes = parse_input_file(f)
    assert nodes == {}


def test_parse_input_file_no_routing(tmp_path):
    """Lines with exactly 3 parts (no routing) have empty routing string."""
    f = tmp_path / "test.txt"
    f.write_text("mynode CLI aabbccdd\n")
    nodes = parse_input_file(f)
    assert nodes["aabbccdd"]["routing"] == ""


# ---------------------------------------------------------------------------
# is_input_node
# ---------------------------------------------------------------------------

def test_is_input_node_matches_input_source():
    db = {"nodes": {"aabbccdd": {"name": "n", "source": "nodes.txt"}}}
    assert is_input_node("aabbccdd", db) is True


def test_is_input_node_rejects_api_source():
    db = {"nodes": {"aabbccdd": {"name": "n", "source": "api:LUX"}}}
    assert is_input_node("aabbccdd", db) is False


def test_is_input_node_rejects_advert_source():
    db = {"nodes": {"aabbccdd": {"name": "n", "source": "advert"}}}
    assert is_input_node("aabbccdd", db) is False


def test_is_input_node_no_match():
    db = {"nodes": {"aabbccdd": {"name": "n", "source": "nodes.txt"}}}
    assert is_input_node("deadbeef", db) is False


# ---------------------------------------------------------------------------
# is_blacklisted
# ---------------------------------------------------------------------------

def test_is_blacklisted_empty_blacklist():
    db = {"nodes": {"aabbccdd": {"name": "bad-node"}}}
    assert is_blacklisted("aabbccdd", db, []) is False


def test_is_blacklisted_name_match():
    db = {"nodes": {"aabbccdd": {"name": "bad-node"}}}
    assert is_blacklisted("aabbccdd", db, ["bad"]) is True


def test_is_blacklisted_hex_prefix_match():
    db = {"nodes": {}}
    assert is_blacklisted("aabbccdd", db, ["aabb"]) is True


def test_is_blacklisted_no_match():
    db = {"nodes": {"aabbccdd": {"name": "good-node"}}}
    assert is_blacklisted("aabbccdd", db, ["evil"]) is False


def test_is_blacklisted_no_db_entry_no_hex_match():
    db = {"nodes": {}}
    assert is_blacklisted("aabbccdd", db, ["xxxx"]) is False


# ---------------------------------------------------------------------------
# resolve_name_filtered
# ---------------------------------------------------------------------------

def test_resolve_name_filtered_no_blacklist():
    db = {"nodes": {"aabbccdd": {"name": "my-node"}}}
    assert resolve_name_filtered("aabbccdd", db, []) == "my-node"


def test_resolve_name_filtered_blacklist_removes_name():
    db = {"nodes": {"aabbccdd": {"name": "LocalNode"}}}
    assert resolve_name_filtered("aabbccdd", db, ["LocalNode"]) is None


def test_resolve_name_filtered_partial_blacklist():
    db = {"nodes": {
        "aabb1111": {"name": "LocalNode"},
        "aabb2222": {"name": "Rasta"},
    }}
    result = resolve_name_filtered("aabb", db, ["LocalNode"])
    assert result is not None
    assert "Rasta" in result
    assert "LocalNode" not in result


def test_resolve_name_filtered_no_db_match():
    db = {"nodes": {}}
    assert resolve_name_filtered("deadbeef", db, ["bad"]) == "deadbeef"


# ---------------------------------------------------------------------------
# update — coord backfill and failure
# ---------------------------------------------------------------------------

def test_update_coord_backfill(tmp_path):
    """Coordinates from coord provider are backfilled into nodes without lat/lon."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    full_key = "aa" * 32
    (input_dir / "test.txt").write_text(f"my-node CLI {full_key}\n")
    db_file = tmp_path / "nodes.json"

    class _StubNodeProvider:
        def fetch_nodes(self, region): return {}

    class _CoordProvider:
        def fetch_node_coords(self):
            return {full_key: {"lat": 49.5, "lon": 6.2}}

    with patch("meshcore_tools.db.INPUT_DIR", input_dir), \
         patch("meshcore_tools.db.DB_FILE", db_file):
        update("LUX", node_provider=_StubNodeProvider(), coord_provider=_CoordProvider())

    db = json.loads(db_file.read_text())
    assert db["nodes"][full_key]["lat"] == 49.5
    assert db["nodes"][full_key]["lon"] == 6.2


def test_update_coord_failure_continues(tmp_path):
    """Coord provider failure is non-fatal; nodes are still saved."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "test.txt").write_text("my-node CLI aabbccdd\n")
    db_file = tmp_path / "nodes.json"

    class _StubNodeProvider:
        def fetch_nodes(self, region): return {}

    class _FailCoordProvider:
        def fetch_node_coords(self): raise Exception("timeout")

    with patch("meshcore_tools.db.INPUT_DIR", input_dir), \
         patch("meshcore_tools.db.DB_FILE", db_file):
        update("LUX", node_provider=_StubNodeProvider(), coord_provider=_FailCoordProvider())

    db = json.loads(db_file.read_text())
    assert "aabbccdd" in db["nodes"]
