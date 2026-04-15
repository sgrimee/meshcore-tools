"""Tests for lma.map_view helper functions."""

import struct

from meshcore_tools.disambiguation import ResolvedHop
from meshcore_tools.map_view import _build_footer, _lookup_coords, collect_map_nodes


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


def test_lookup_coords_remote_fallback():
    """Falls back to remote_coords when db has no match."""
    db = {"nodes": {}}
    remote = {"aabbccdd" * 4: {"lat": 49.5, "lon": 6.2}}
    assert _lookup_coords("aabbccdd" * 4, db, remote_coords=remote) == (49.5, 6.2)


def test_lookup_coords_db_wins_over_remote():
    """DB takes priority over remote_coords for the same key."""
    key = "aabbccdd" * 4
    db = {"nodes": {key: {"lat": 1.0, "lon": 2.0}}}
    remote = {key: {"lat": 99.0, "lon": 99.0}}
    assert _lookup_coords(key, db, remote_coords=remote) == (1.0, 2.0)


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
    assert "my-gateway" in placed[0][0]


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
    obs_entry = next((label for label in roles if "obs-node" in label), None)
    assert obs_entry is not None
    assert roles[obs_entry] == "observer"


def test_collect_map_nodes_unplaced_when_no_coords():
    db = {"nodes": {}}
    packet = _flood_textmsg_packet(src_hash="aabbccdd", origin_id="deadbeef", path=[])
    placed, unplaced, _ = collect_map_nodes(packet, db)
    assert placed == []
    assert len(unplaced) >= 1


def test_collect_map_nodes_path_segments_order():
    """path_segments should be source→relay and relay→observer, both solid."""
    src_key = "aa" * 4
    relay_key = "bb" * 4
    obs_key = "cc" * 4
    # Use coordinates ~11 km apart (well within the 150 km LoRa guard)
    db = {
        "nodes": {
            src_key: {"lat": 49.0, "lon": 6.0, "name": "src"},
            relay_key: {"lat": 49.1, "lon": 6.0, "name": "relay"},
            obs_key: {"lat": 49.2, "lon": 6.0, "name": "obs"},
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
    placed, _, path_segments = collect_map_nodes(packet, db)
    assert len(path_segments) == 2
    start0, end0, solid0 = path_segments[0]
    start1, end1, solid1 = path_segments[1]
    assert start0 == (49.0, 6.0)   # source
    assert end0 == (49.1, 6.0)     # relay
    assert start1 == (49.1, 6.0)   # relay
    assert end1 == (49.2, 6.0)     # observer
    assert solid0 is True
    assert solid1 is True


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
    assert any("ResolvedRelay" in lbl for lbl in labels)
    # DB name for relay must NOT appear (resolved name took precedence)
    assert not any("db-relay-name" in lbl for lbl in labels)

    # Verify the resolved coords were used
    relay_entry = next((e for e in placed if "ResolvedRelay" in e[0]), None)
    assert relay_entry is not None
    assert abs(relay_entry[2] - 49.5) < 0.001
    assert abs(relay_entry[3] - 6.5) < 0.001


# ---------------------------------------------------------------------------
# Path segment gap detection
# ---------------------------------------------------------------------------

def test_path_segments_solid_when_all_relays_placed():
    """All relays with coords → all segments solid."""
    src_key = "aa" * 4
    r1_key = "bb" * 4
    r2_key = "cc" * 4
    obs_key = "dd" * 4
    # Use coordinates ~5.5 km apart (well within the 150 km LoRa guard)
    db = {
        "nodes": {
            src_key: {"lat": 49.0, "lon": 6.0, "name": "src"},
            r1_key: {"lat": 49.05, "lon": 6.0, "name": "r1"},
            r2_key: {"lat": 49.1, "lon": 6.0, "name": "r2"},
            obs_key: {"lat": 49.15, "lon": 6.0, "name": "obs"},
        }
    }
    packet = {
        "raw_data": "",
        "_route_type": "Flood",
        "_src_hash": src_key,
        "_path": [src_key, r1_key, r2_key],
        "origin_id": obs_key,
    }
    _, _, path_segments = collect_map_nodes(packet, db)
    assert all(solid for _, _, solid in path_segments)


def test_path_segments_dashed_for_unplaced_relay():
    """An unplaced relay between two placed nodes produces a dashed segment."""
    src_key = "aa" * 4
    relay_hash = "bb"  # short hash, not in DB
    obs_key = "cc" * 4
    # Use Luxembourg-area coordinates ~14 km apart (well within the 150 km LoRa guard)
    src_lat, src_lon = 49.6, 6.1
    obs_lat, obs_lon = 49.7, 6.2
    db = {
        "nodes": {
            src_key: {"lat": src_lat, "lon": src_lon, "name": "src"},
            obs_key: {"lat": obs_lat, "lon": obs_lon, "name": "obs"},
            # relay_hash deliberately absent → unplaced
        }
    }
    hop = ResolvedHop(
        raw_hash=relay_hash,
        resolved_key=None,
        name="UnknownRelay",
        lat=None,
        lon=None,
        confidence="unknown",
    )
    packet = {
        "raw_data": "",
        "_route_type": "Flood",
        "_src_hash": src_key,
        "_path": [src_key, relay_hash],
        "origin_id": obs_key,
    }
    placed, unplaced, path_segments = collect_map_nodes(
        packet, db, resolved_hops=[hop]
    )
    # One dashed segment spans the gap: src → obs (relay was unplaced)
    assert any(not solid for _, _, solid in path_segments), \
        "Expected at least one dashed segment"
    # The dashed segment must connect source to observer
    dashed = [(s, e) for s, e, solid in path_segments if not solid]
    assert len(dashed) == 1
    assert dashed[0][0] == (src_lat, src_lon)  # source
    assert dashed[0][1] == (obs_lat, obs_lon)  # observer


def test_path_segments_consecutive_unplaced_produce_single_dashed():
    """Two consecutive unplaced relays produce one dashed segment, not two."""
    src_key = "aa" * 4
    obs_key = "dd" * 4
    # Use Luxembourg-area coordinates ~28 km apart (well within the 150 km LoRa guard)
    db = {
        "nodes": {
            src_key: {"lat": 49.6, "lon": 6.1, "name": "src"},
            obs_key: {"lat": 49.8, "lon": 6.3, "name": "obs"},
        }
    }
    hops = [
        ResolvedHop("bb", None, "X", None, None, "unknown"),
        ResolvedHop("cc", None, "Y", None, None, "unknown"),
    ]
    packet = {
        "raw_data": "",
        "_route_type": "Flood",
        "_src_hash": src_key,
        "_path": [src_key, "bb", "cc"],
        "origin_id": obs_key,
    }
    _, _, path_segments = collect_map_nodes(packet, db, resolved_hops=hops)
    dashed = [(s, e) for s, e, solid in path_segments if not solid]
    assert len(dashed) == 1, "Two consecutive gaps should collapse into one dashed segment"


def test_path_segments_blacklisted_relay_no_gap():
    """A blacklisted relay between two placed nodes does NOT create a gap."""
    src_key = "aa" * 4
    obs_key = "cc" * 4
    bl_key = "bb" * 4
    # Use Luxembourg-area coordinates ~25 km apart (well within the 150 km LoRa guard)
    db = {
        "nodes": {
            src_key: {"lat": 49.5, "lon": 6.0, "name": "src"},
            obs_key: {"lat": 49.7, "lon": 6.2, "name": "obs"},
            bl_key: {"lat": 49.6, "lon": 6.1, "name": "bad-relay"},
        }
    }
    packet = {
        "raw_data": "",
        "_route_type": "Flood",
        "_src_hash": src_key,
        "_path": [src_key, bl_key],
        "origin_id": obs_key,
    }
    _, _, path_segments = collect_map_nodes(
        packet, db, blacklist=["bad-relay"]
    )
    # All remaining segments should be solid (blacklisted relay is removed, not a gap)
    assert all(solid for _, _, solid in path_segments), \
        "Blacklisted relay should not produce a dashed segment"


def test_collect_map_nodes_remote_coords_resolves_unplaced():
    """A unique relay with no DB coords gets placed when remote_coords has its key."""
    src_key = "aa" * 4
    relay_key = "bb" * 32  # 64-char key
    obs_key = "cc" * 4
    # Use coordinates ~11 km apart (well within the 150 km LoRa guard)
    db = {
        "nodes": {
            src_key: {"lat": 49.0, "lon": 6.0, "name": "src"},
            relay_key: {"name": "relay-no-gps"},  # in DB but no lat/lon
            obs_key: {"lat": 49.2, "lon": 6.0, "name": "obs"},
        }
    }
    remote = {relay_key: {"lat": 49.1, "lon": 6.0}}
    hop = ResolvedHop(
        raw_hash=relay_key[:4],
        resolved_key=relay_key,
        name="relay-no-gps",
        lat=None,
        lon=None,
        confidence="unique",
    )
    packet = {
        "raw_data": "",
        "_route_type": "Flood",
        "_src_hash": src_key,
        "_path": [src_key, relay_key[:4]],
        "origin_id": obs_key,
    }
    placed, unplaced, path_segments = collect_map_nodes(
        packet, db, resolved_hops=[hop], remote_coords=remote
    )
    relay_labels = [label for label, role, _, _ in placed if role == "relay"]
    assert any("relay-no-gps" in lbl for lbl in relay_labels), "Remote coords should have placed the relay"
    assert not any("relay-no-gps" in lbl for lbl in unplaced)
    # All segments should now be solid
    assert all(solid for _, _, solid in path_segments)


def test_unknown_relay_not_placed_via_remote_coords():
    """confidence='unknown' relay must NOT be placed using remote_coords.

    A short hop hash like '66' can prefix-match any worldwide node in remote_coords.
    Placing it would put the relay on the wrong continent. The relay must stay unplaced.
    """
    src_key = "aa" * 4
    obs_key = "cc" * 4
    relay_hash = "66"  # 1-byte hash, unknown (no local DB match)
    far_away_key = "66" + "bb" * 31  # 64-char key starting with "66", far-away node

    db = {
        "nodes": {
            src_key: {"lat": 49.0, "lon": 6.0, "name": "src"},
            obs_key: {"lat": 49.5, "lon": 6.5, "name": "obs"},
            # relay_hash deliberately absent
        }
    }
    remote = {far_away_key: {"lat": -34.0, "lon": -70.0}}  # South America

    hop = ResolvedHop(
        raw_hash=relay_hash,
        resolved_key=None,
        name=relay_hash[:8],
        lat=None,
        lon=None,
        confidence="unknown",
    )
    packet = {
        "raw_data": "",
        "_route_type": "Flood",
        "_src_hash": src_key,
        "_path": [src_key, relay_hash],
        "origin_id": obs_key,
    }
    placed, unplaced, _ = collect_map_nodes(
        packet, db, resolved_hops=[hop], remote_coords=remote
    )
    relay_lats = [lat for _, role, lat, _ in placed if role == "relay"]
    assert not relay_lats, "Unknown relay must not be placed via remote_coords"
    assert any(relay_hash[:8] in lbl for lbl in unplaced), "Unknown relay must be in unplaced"


def test_unique_local_relay_no_local_coords_placed_via_remote():
    """A relay with exactly one local DB entry (but no local coords) is placed via remote_coords.

    When n_candidates==1 we know the full DB key, so we can safely look up
    remote_coords — no short-hash ambiguity.  This covers both the rh-is-None
    fallback and the no-resolved-hops else branch.
    """
    src_key = "aa" * 4
    obs_key = "cc" * 4
    relay_key = "bb" * 32  # 64-char key, in local DB but no coords there
    relay_hash = relay_key[:4]  # short hash used in the packet path

    db = {
        "nodes": {
            src_key: {"lat": 49.0, "lon": 6.0, "name": "src"},
            obs_key: {"lat": 49.5, "lon": 6.5, "name": "obs"},
            relay_key: {"name": "relay-no-gps"},  # in DB, no lat/lon
        }
    }
    remote = {relay_key: {"lat": 49.2, "lon": 6.1}}  # nearby, plausible

    packet = {
        "raw_data": "",
        "_route_type": "Flood",
        "_src_hash": src_key,
        "_path": [src_key, relay_hash],
        "origin_id": obs_key,
    }

    # rh-is-None fallback (resolved_hops=[] so relay falls through)
    placed, unplaced, _ = collect_map_nodes(
        packet, db, resolved_hops=[], remote_coords=remote
    )
    relay_entries = [(lat, lon) for _, role, lat, lon in placed if role == "relay"]
    assert relay_entries, "Relay with one local match should be placed via remote_coords"
    assert abs(relay_entries[0][0] - 49.2) < 0.001

    # No-resolved-hops else branch (resolved_hops=None)
    placed2, unplaced2, _ = collect_map_nodes(
        packet, db, resolved_hops=None, remote_coords=remote
    )
    relay_entries2 = [(lat, lon) for _, role, lat, lon in placed2 if role == "relay"]
    assert relay_entries2, "Relay with one local match should be placed via remote_coords (no-resolved-hops path)"
    assert abs(relay_entries2[0][0] - 49.2) < 0.001


def test_partial_key_relay_not_placed_via_remote_coords():
    """A relay resolved to a PARTIAL DB key must not use remote_coords.

    Partial keys (< 64 hex chars) prefix-match any worldwide node that starts
    with the same prefix — exactly the wrong-continent placement bug.
    Only full 64-char keys are safe to use against remote_coords.
    """
    src_key = "aa" * 4
    obs_key = "cc" * 4
    relay_partial = "3e"          # partial key in local DB (user-configured)
    relay_hash = "3e"             # hop hash matches
    far_away_key = "3e" + "bb" * 31  # full remote key starting with "3e" — North America

    db = {
        "nodes": {
            src_key: {"lat": 49.0, "lon": 6.0, "name": "src"},
            obs_key: {"lat": 49.5, "lon": 6.5, "name": "obs"},
            relay_partial: {"name": "Meshnet.lu RPT 8", "key_complete": False},
        }
    }
    remote = {far_away_key: {"lat": 45.0, "lon": -75.0}}  # Ottawa, Canada

    hop = ResolvedHop(
        raw_hash=relay_hash,
        resolved_key=relay_partial,   # partial key — NOT safe for remote lookup
        name="Meshnet.lu RPT 8",
        lat=None,
        lon=None,
        confidence="unique",
    )
    packet = {
        "raw_data": "",
        "_route_type": "Flood",
        "_src_hash": src_key,
        "_path": [src_key, relay_hash],
        "origin_id": obs_key,
    }
    placed, unplaced, _ = collect_map_nodes(
        packet, db, resolved_hops=[hop], remote_coords=remote
    )
    relay_lats = [lat for _, role, lat, _ in placed if role == "relay"]
    assert not relay_lats, (
        "Relay with partial DB key must not be placed via remote_coords "
        f"(got lats: {relay_lats})"
    )


def test_no_local_match_relay_not_placed_via_remote_coords():
    """A relay not in resolved_hops (rh is None) with n_candidates==0 must not use remote_coords."""
    src_key = "aa" * 4
    obs_key = "cc" * 4
    relay_hash = "66"
    far_away_key = "66" + "bb" * 31

    db = {
        "nodes": {
            src_key: {"lat": 49.0, "lon": 6.0, "name": "src"},
            obs_key: {"lat": 49.5, "lon": 6.5, "name": "obs"},
        }
    }
    remote = {far_away_key: {"lat": -34.0, "lon": -70.0}}  # South America

    # Pass resolved_hops=[] so relay_hash falls into the rh-is-None fallback
    packet = {
        "raw_data": "",
        "_route_type": "Flood",
        "_src_hash": src_key,
        "_path": [src_key, relay_hash],
        "origin_id": obs_key,
    }
    placed, unplaced, _ = collect_map_nodes(
        packet, db, resolved_hops=[], remote_coords=remote
    )
    relay_lats = [lat for _, role, lat, _ in placed if role == "relay"]
    assert not relay_lats, "Relay with no local DB match must not be placed via remote_coords"


def test_relay_beyond_lora_range_not_placed():
    """A relay >150 km from all anchors must be rejected even when it has a full key.

    This is the case seen in the screenshot: a node with a full 64-char key has
    remote_coords in North America while the path is entirely in Luxembourg.
    The 150 km hard LoRa cutoff must prevent the placement.
    """
    src_key = "aa" * 32   # 64-char key, Luxembourg
    obs_key = "cc" * 32   # 64-char key, Luxembourg
    relay_key = "bb" * 32  # 64-char key, node named "08" or similar

    db = {
        "nodes": {
            src_key: {"lat": 49.6, "lon": 6.1, "name": "src-lux"},
            obs_key: {"lat": 49.7, "lon": 6.2, "name": "obs-lux"},
            relay_key: {"name": "08"},  # in local DB, no local coords
        }
    }
    # Remote has this node at a North American location (~5500 km away)
    remote = {relay_key: {"lat": 45.4, "lon": -75.7}}  # Ottawa, Canada

    hop = ResolvedHop(
        raw_hash=relay_key[:4],
        resolved_key=relay_key,
        name="08",
        lat=None,
        lon=None,
        confidence="unique",
    )
    packet = {
        "raw_data": "",
        "_route_type": "Flood",
        "_src_hash": src_key,
        "_path": [src_key, relay_key[:4]],
        "origin_id": obs_key,
    }
    placed, unplaced, _ = collect_map_nodes(
        packet, db, resolved_hops=[hop], remote_coords=remote
    )
    relay_lats = [lat for _, role, lat, _ in placed if role == "relay"]
    assert not relay_lats, (
        f"Relay >150 km from all anchors must be rejected (got lats: {relay_lats})"
    )


# ---------------------------------------------------------------------------
# _build_footer — unplaced node names
# ---------------------------------------------------------------------------

def test_build_footer_shows_node_names():
    """Unplaced nodes are listed by name, not just counted."""
    placed: list = []
    unplaced = ["alpha", "beta"]
    footer = _build_footer(placed, unplaced)
    assert "alpha" in footer
    assert "beta" in footer


def test_build_footer_truncates_long_unplaced_list():
    """More than 5 unplaced nodes show first 5 names plus overflow count."""
    placed: list = []
    unplaced = [f"node{i}" for i in range(8)]
    footer = _build_footer(placed, unplaced)
    # First 5 names visible, rest summarised
    for i in range(5):
        assert f"node{i}" in footer
    assert "+3 more" in footer
    # Names beyond the cutoff must not appear verbatim
    for i in range(5, 8):
        assert f"node{i}" not in footer


def test_build_footer_exactly_five_unplaced_no_overflow():
    """Exactly 5 unplaced nodes are all shown with no '+N more' suffix."""
    placed: list = []
    unplaced = [f"node{i}" for i in range(5)]
    footer = _build_footer(placed, unplaced)
    for i in range(5):
        assert f"node{i}" in footer
    assert "more" not in footer


# ---------------------------------------------------------------------------
# collect_map_nodes — Path packet dest_hash (dst_hash key fix)
# ---------------------------------------------------------------------------

def _make_path_packet_hex(src_hash: bytes, dst_hash: bytes) -> bytes:
    """Build a minimal Flood+Path raw packet with the given src and dst hashes."""
    hash_size = len(src_hash)
    assert len(dst_hash) == hash_size
    header = (0x08 << 2) | 0x01  # Flood | Path
    # path_len byte: hash_size-1 in bits 7-6, 0 hops in bits 5-0
    path_len_byte = ((hash_size - 1) << 6) | 0x00
    payload = src_hash + dst_hash
    return bytes([header, path_len_byte]) + payload


def _path_packet_dict(src_key: str, dst_key: str, origin_id: str) -> dict:
    """Build a pre-decoded Path packet dict."""
    hash_size = 2  # 2-byte hashes for test clarity
    src_bytes = bytes.fromhex(src_key[:hash_size * 2])
    dst_bytes = bytes.fromhex(dst_key[:hash_size * 2])
    raw_hex = _make_path_packet_hex(src_bytes, dst_bytes).hex()
    return {
        "raw_data": raw_hex,
        "origin_id": origin_id,
    }


def test_collect_map_nodes_path_dest_placed():
    """Path packets expose dst_hash; dest should be placed when coords are available."""
    # Use 2-byte hashes → hash_size=2
    src_key = "aa" * 32   # 64-char full key; first 4 hex chars = "aaaa"
    dst_key = "bb" * 32   # first 4 hex chars = "bbbb"
    obs_key = "cc" * 4

    db = {
        "nodes": {
            src_key: {"lat": 49.0, "lon": 6.0, "name": "src-node"},
            dst_key: {"lat": 49.1, "lon": 6.1, "name": "dst-node"},
            obs_key: {"lat": 49.2, "lon": 6.2, "name": "obs-node"},
        }
    }
    packet = _path_packet_dict(src_key, dst_key, obs_key)
    placed, unplaced, _ = collect_map_nodes(packet, db)

    roles = {role for _, role, _, _ in placed}
    assert "dest" in roles, f"dest should be placed for Path packet; placed roles: {roles}"
    dest_entry = next((e for e in placed if e[1] == "dest"), None)
    assert dest_entry is not None
    assert abs(dest_entry[2] - 49.1) < 0.001


# ---------------------------------------------------------------------------
# collect_map_nodes — geo-scoring for ambiguous 1-byte source/dest
# ---------------------------------------------------------------------------

def test_geo_scoring_resolves_ambiguous_source():
    """When src_hash matches two DB nodes, the one within LoRa range is chosen."""
    # Both nodes share the same 1-byte hash prefix "aa"
    near_src  = "aa" * 4 + "11" * 28   # starts with "aa", geographically close
    far_src   = "aa" * 4 + "22" * 28   # same 1-byte prefix, geographically far away
    relay_key = "bb" * 4
    obs_key   = "cc" * 4

    # near_src is ~11 km from relay (within 150 km); far_src is on another continent
    db = {
        "nodes": {
            near_src:  {"lat": 49.1, "lon": 6.0, "name": "near-source"},
            far_src:   {"lat": -33.9, "lon": 151.2, "name": "far-source"},  # Sydney
            relay_key: {"lat": 49.0, "lon": 6.0, "name": "relay"},
            obs_key:   {"lat": 49.2, "lon": 6.0, "name": "observer"},
        }
    }
    # Packet with 1-byte src_hash "aa" (matches both near_src and far_src)
    packet = {
        "raw_data": "",
        "_route_type": "Flood",
        "_src_hash": "aa",          # 1-byte → ambiguous without geo-scoring
        "_path": [relay_key],
        "origin_id": obs_key,
    }
    placed, unplaced, _ = collect_map_nodes(packet, db)

    src_entries = [(label, lat, lon) for label, role, lat, lon in placed if role == "source"]
    assert len(src_entries) == 1, (
        f"Geo-scoring should select exactly one source; placed: {src_entries}"
    )
    assert "near-source" in src_entries[0][0]
    assert "far-source" not in (label for label, _, _ in src_entries)


def test_geo_scoring_leaves_ambiguous_source_unplaced():
    """If two candidates are both within LoRa range, source stays unplaced."""
    near1 = "aa" * 4 + "11" * 28
    near2 = "aa" * 4 + "22" * 28
    relay_key = "bb" * 4
    obs_key   = "cc" * 4

    db = {
        "nodes": {
            near1:     {"lat": 49.1, "lon": 6.0, "name": "near1"},
            near2:     {"lat": 49.15, "lon": 6.05, "name": "near2"},  # also nearby
            relay_key: {"lat": 49.0, "lon": 6.0, "name": "relay"},
            obs_key:   {"lat": 49.2, "lon": 6.0, "name": "observer"},
        }
    }
    packet = {
        "raw_data": "",
        "_route_type": "Flood",
        "_src_hash": "aa",
        "_path": [relay_key],
        "origin_id": obs_key,
    }
    placed, unplaced, _ = collect_map_nodes(packet, db)
    src_entries = [e for e in placed if e[1] == "source"]
    assert not src_entries, "Both candidates in range → source must stay unplaced"
