"""Tests for lma.map_view helper functions."""

import struct

from meshcore_tools.disambiguation import ResolvedHop
from meshcore_tools.map_view import _lookup_coords, collect_map_nodes


# ---------------------------------------------------------------------------
# _lookup_coords
# ---------------------------------------------------------------------------

def test_lookup_coords_exact_match():
    db = {"nodes": {"aabbccdd": {"lat": 49.5, "lon": 6.2}}}
    assert _lookup_coords("aabbccdd", db) == (49.5, 6.2)


def test_lookup_coords_prefix_match():
    db = {"nodes": {"aabbccdd11223344": {"lat": 1.0, "lon": 2.0}}}
    assert _lookup_coords("aabbccdd", db) == (1.0, 2.0)


def test_lookup_coords_no_match():
    db = {"nodes": {"aabbccdd": {"lat": 1.0, "lon": 2.0}}}
    assert _lookup_coords("deadbeef", db) is None


def test_lookup_coords_missing_lat():
    db = {"nodes": {"aabbccdd": {"lon": 6.2}}}
    assert _lookup_coords("aabbccdd", db) is None


def test_lookup_coords_missing_lon():
    db = {"nodes": {"aabbccdd": {"lat": 49.5}}}
    assert _lookup_coords("aabbccdd", db) is None


# ---------------------------------------------------------------------------
# collect_map_nodes helpers
# ---------------------------------------------------------------------------

def _make_advert_hex(pub_key: bytes, lat: float, lon: float, name: str) -> bytes:
    """Build a minimal Flood+Advert packet with location and name."""
    header = 0x11  # Flood(0x01) | Advert(0x04 << 2)
    path_byte = 0x00
    timestamp = struct.pack("<I", 0)
    signature = b"\x00" * 64
    flags = 0x91  # role=ChatNode(1) | HasLocation(0x10) | HasName(0x80)
    lat_bytes = struct.pack("<i", int(lat * 1_000_000))
    lon_bytes = struct.pack("<i", int(lon * 1_000_000))
    payload = pub_key[:32] + timestamp + signature + bytes([flags]) + lat_bytes + lon_bytes + name.encode() + b"\x00"
    return bytes([header, path_byte]) + payload


# ---------------------------------------------------------------------------
# collect_map_nodes — Advert packet
# ---------------------------------------------------------------------------

def test_collect_map_nodes_advert_coords_from_payload():
    pub = b"\x01" * 32
    raw_hex = _make_advert_hex(pub, lat=49.5, lon=6.2, name="gw-test").hex()
    packet = {"raw_data": raw_hex}
    db = {"nodes": {}}
    placed, unplaced, _ = collect_map_nodes(packet, db)
    assert len(placed) == 1
    label, role, lat, lon = placed[0]
    assert role == "source"
    assert abs(lat - 49.5) < 0.001
    assert abs(lon - 6.2) < 0.001


def test_collect_map_nodes_advert_label_from_db():
    pub = b"\x02" * 32
    raw_hex = _make_advert_hex(pub, lat=49.0, lon=6.0, name="gw").hex()
    packet = {"raw_data": raw_hex}
    db = {"nodes": {pub.hex(): {"name": "my-gateway"}}}
    placed, _, _ = collect_map_nodes(packet, db)
    assert placed[0][0] == "my-gateway"


# ---------------------------------------------------------------------------
# collect_map_nodes — non-Advert packet using _-prefixed fallback fields
# ---------------------------------------------------------------------------

def _flood_textmsg_packet(src_hash: str, origin_id: str, path: list[str]) -> dict:
    """Packet dict with no raw_data but pre-set fallback fields."""
    return {
        "raw_data": "",
        "_route_type": "Flood",
        "_src_hash": src_hash,
        "_path": path,
        "origin_id": origin_id,
    }


def test_collect_map_nodes_observer_from_db():
    db = {"nodes": {"aabbccdd": {"lat": 49.0, "lon": 6.0, "name": "obs-node"}}}
    packet = _flood_textmsg_packet(src_hash="deadbeef", origin_id="aabbccdd", path=[])
    placed, unplaced, _ = collect_map_nodes(packet, db)
    roles = {label: role for label, role, _, _ in placed}
    assert "obs-node" in roles
    assert roles["obs-node"] == "observer"


def test_collect_map_nodes_unplaced_when_no_coords():
    db = {"nodes": {}}
    packet = _flood_textmsg_packet(src_hash="aabbccdd", origin_id="deadbeef", path=[])
    placed, unplaced, _ = collect_map_nodes(packet, db)
    assert placed == []
    assert len(unplaced) >= 1


def test_collect_map_nodes_path_coords_order():
    """path_coords should be source → relays → observer."""
    src_key = "aa" * 4
    relay_key = "bb" * 4
    obs_key = "cc" * 4
    db = {
        "nodes": {
            src_key: {"lat": 1.0, "lon": 1.0, "name": "src"},
            relay_key: {"lat": 2.0, "lon": 2.0, "name": "relay"},
            obs_key: {"lat": 3.0, "lon": 3.0, "name": "obs"},
        }
    }
    # For Direct: all path entries are relays; src_hash is explicit
    packet = {
        "raw_data": "",
        "_route_type": "Direct",
        "_src_hash": src_key,
        "_path": [relay_key],
        "origin_id": obs_key,
    }
    placed, _, path_coords = collect_map_nodes(packet, db)
    assert path_coords[0] == (1.0, 1.0)   # source first
    assert path_coords[1] == (2.0, 2.0)   # relay in middle
    assert path_coords[2] == (3.0, 3.0)   # observer last


def test_collect_map_nodes_dedup_same_coords():
    """When observer and source share coords, only one placed entry with role 'source'."""
    key = "aabbccdd"
    db = {"nodes": {key: {"lat": 49.0, "lon": 6.0, "name": "shared"}}}
    packet = {
        "raw_data": "",
        "_route_type": "Direct",
        "_src_hash": key,
        "_path": [],
        "origin_id": key,
    }
    placed, _, _ = collect_map_nodes(packet, db)
    assert len(placed) == 1
    assert placed[0][1] == "source"


# ---------------------------------------------------------------------------
# collect_map_nodes — resolved_hops parameter
# ---------------------------------------------------------------------------

def test_collect_map_nodes_uses_resolved_hops():
    """collect_map_nodes places relay using ResolvedHop name and coords, not DB lookup."""
    relay_hash = "bbbbbbbb"
    src_hash = "aaaaaaaa"

    # DB has a different name and no coords for the relay
    db = {
        "nodes": {
            src_hash: {"lat": 49.0, "lon": 6.0, "name": "source-node"},
            relay_hash: {"name": "db-relay-name"},
        }
    }

    hop = ResolvedHop(
        raw_hash=relay_hash,
        resolved_key=relay_hash,
        name="ResolvedRelay",
        lat=49.5,
        lon=6.5,
        confidence="unique",
    )

    # Direct route: all path entries are relays
    packet = {
        "raw_data": "",
        "_route_type": "Direct",
        "_src_hash": src_hash,
        "_path": [relay_hash],
        "origin_id": "",
    }

    placed, unplaced, _ = collect_map_nodes(packet, db, resolved_hops=[hop])

    labels = [label for label, _, _, _ in placed]
    assert "ResolvedRelay" in labels
    # DB name for relay must NOT appear (resolved name took precedence)
    assert "db-relay-name" not in labels

    # Verify the resolved coords were used
    relay_entry = next((e for e in placed if e[0] == "ResolvedRelay"), None)
    assert relay_entry is not None
    assert abs(relay_entry[2] - 49.5) < 0.001
    assert abs(relay_entry[3] - 6.5) < 0.001
