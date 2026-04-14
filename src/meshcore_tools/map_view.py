"""Tile map view of nodes involved in a packet.

Requires optional dependencies:
    pip install "meshcore-tools[map]"   # textual-image, staticmap, Pillow
"""

from __future__ import annotations

import hashlib
import math
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import logging

from rich.markup import escape as markup_escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from meshcore_tools.db import is_blacklisted, resolve_name
from meshcore_tools.decoder import GROUP_TYPES, decode_packet
from meshcore_tools.disambiguation import _candidates_for, resolve_path_hops

if TYPE_CHECKING:
    from meshcore_tools.disambiguation import ResolvedHop

logger = logging.getLogger(__name__)

try:
    from staticmap import CircleMarker, Line, StaticMap
    from textual_image._terminal import get_cell_size as _get_cell_size
    from textual_image.widget import Image as TileImage
    _HAS_MAP_LIBS = True
except ImportError:
    StaticMap = None  # type: ignore
    CircleMarker = None  # type: ignore
    Line = None  # type: ignore
    TileImage = None  # type: ignore
    _get_cell_size = None  # type: ignore
    _HAS_MAP_LIBS = False

_TILE_CACHE = Path.home() / ".cache" / "lma" / "tiles"

_ROLE_PRIORITY = {"source": 0, "observer": 1, "relay": 2, "dest": 3}
_ROLE_COLORS = {
    "source": ("#44ff44", "green"),
    "observer": ("#ffff44", "yellow"),
    "relay": ("#44ffff", "cyan"),
    "dest": ("#ff4444", "red"),
}

# ---------------------------------------------------------------------------
# Remote coordinate cache (fetched once per session from map.meshcore.dev)
# ---------------------------------------------------------------------------

_remote_coords: dict[str, dict] = {}
_remote_coords_fetched: bool = False
_remote_coords_lock: threading.Lock = threading.Lock()


def _ensure_remote_coords() -> dict[str, dict]:
    """Fetch GPS coordinates from map.meshcore.dev once per session.

    Safe to call from multiple threads. Returns cached result on subsequent calls.
    """
    global _remote_coords, _remote_coords_fetched
    with _remote_coords_lock:
        if not _remote_coords_fetched:
            try:
                from meshcore_tools.providers.meshcore_rest import MeshcoreRestProvider
                _remote_coords = MeshcoreRestProvider().fetch_node_coords()
                logger.debug("Fetched remote coords for %d nodes", len(_remote_coords))
            except Exception as e:
                logger.warning("Failed to fetch remote node coords: %s", e)
            _remote_coords_fetched = True
    return _remote_coords


# PathSegment: (start_latlon, end_latlon, is_solid)
# is_solid=True  → solid line (consecutive placed nodes, no gap between them)
# is_solid=False → dashed line (one or more unplaced nodes between the endpoints)
PathSegment = tuple[tuple[float, float], tuple[float, float], bool]


def _route_order_to_segments(
    route_order: list[tuple[float, float] | None],
) -> list[PathSegment]:
    """Convert an ordered list of placed-coords or None to path segments.

    Consecutive None entries (unresolved hops) collapse into a single dashed
    segment between the surrounding placed nodes.
    """
    segments: list[PathSegment] = []
    prev: tuple[float, float] | None = None
    has_gap = False
    for coord in route_order:
        if coord is None:
            has_gap = True
        else:
            if prev is not None:
                segments.append((prev, coord, not has_gap))
            prev = coord
            has_gap = False
    return segments


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

# Hard physical LoRa range limit: matches _LORA_HARD_CUTOFF_KM in disambiguation.py
_RELAY_MAX_KM = 150.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km (Haversine)."""
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ, dλ = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _guard_relay_range(
    coords: tuple[float, float] | None,
    anchors: list[tuple[float, float]],
    label: str,
    max_dist_km: float = _RELAY_MAX_KM,
) -> tuple[float, float] | None:
    """Return None when coords are physically impossible for a LoRa relay.

    A relay is rejected when at least one anchor is known AND the candidate
    position is more than max_dist_km from every anchor.  When no anchors
    are available the coords are returned unchanged (graceful degradation).
    """
    if coords is None or not anchors:
        return coords
    if any(
        _haversine_km(coords[0], coords[1], a[0], a[1]) <= max_dist_km
        for a in anchors
    ):
        return coords
    logger.debug(
        "map: relay %r at %s rejected — >%.0f km from all anchors",
        label, coords, max_dist_km,
    )
    return None


def _geo_resolve_hash(
    node_hash: str,
    db: dict,
    anchors: list[tuple[float, float]],
    remote_coords: dict[str, dict] | None,
    max_dist_km: float,
) -> tuple[str, tuple[float, float]] | None:
    """Try to disambiguate a short node hash using geographic filtering.

    Looks up all DB candidates for node_hash, then keeps only those whose
    known coordinates are within max_dist_km of at least one anchor position.
    Returns (full_key, (lat, lon)) when exactly one plausible candidate
    remains, otherwise None.

    This is the Tier-2 geo-scoring equivalent for source/dest hashes.
    """
    if not anchors:
        return None
    candidates = _candidates_for(node_hash, db)
    if len(candidates) < 2:
        return None  # already handled by add_node (unique or unknown)

    plausible: list[tuple[str, tuple[float, float]]] = []
    for key, entry in candidates:
        lat = entry.get("lat")
        lon = entry.get("lon")
        if (lat is None or lon is None) and remote_coords:
            rc = remote_coords.get(key)
            if rc:
                lat, lon = rc.get("lat"), rc.get("lon")
        if lat is None or lon is None:
            continue
        flat, flon = float(lat), float(lon)
        if flat == 0.0 and flon == 0.0:
            continue
        if any(_haversine_km(flat, flon, a[0], a[1]) <= max_dist_km for a in anchors):
            plausible.append((key, (flat, flon)))

    return plausible[0] if len(plausible) == 1 else None


def _lookup_coords(
    node_id: str,
    db: dict,
    remote_coords: dict[str, dict] | None = None,
) -> tuple[float, float] | None:
    """Return (lat, lon) for the first db entry matching node_id as a key prefix.

    Falls back to remote_coords (from map.meshcore.dev) when the db has no match.
    """
    node_id = node_id.lower()
    for key, entry in db.get("nodes", {}).items():
        if key.startswith(node_id) or node_id.startswith(key[: len(node_id)]):
            lat = entry.get("lat")
            lon = entry.get("lon")
            if lat is not None and lon is not None:
                flat, flon = float(lat), float(lon)
                if flat != 0.0 or flon != 0.0:  # (0,0) = Null Island — treat as unknown
                    return (flat, flon)
    if remote_coords:
        for key, coord in remote_coords.items():
            key_l = key.lower()
            if key_l.startswith(node_id) or node_id.startswith(key_l[: len(node_id)]):
                lat = coord.get("lat")
                lon = coord.get("lon")
                if lat is not None and lon is not None:
                    flat, flon = float(lat), float(lon)
                    if flat != 0.0 or flon != 0.0:
                        return (flat, flon)
    return None


# ---------------------------------------------------------------------------
# Node collection
# ---------------------------------------------------------------------------

def collect_map_nodes(
    packet: dict,
    db: dict,
    blacklist: list[str] | None = None,
    resolved_hops: list["ResolvedHop"] | None = None,
    remote_coords: dict[str, dict] | None = None,
    max_relay_dist_km: float = _RELAY_MAX_KM,
) -> tuple[list[tuple[str, str, float, float]], list[str], list[PathSegment]]:
    """Collect nodes involved in a packet with their coordinates.

    Args:
        max_relay_dist_km: Hard cut-off (km) beyond which a relay is treated as
            unplaced.  Defaults to _RELAY_MAX_KM (150 km — hard LoRa limit).
            Set to math.inf to disable the geographic plausibility check.

    Returns:
        placed:        list of (label, role, lat, lon)
        unplaced:      list of labels for nodes without known coordinates
        path_segments: (start, end, is_solid) tuples in routing order
                       (source → relays → observer); is_solid=False indicates
                       one or more unplaced hops between the two endpoints.
    """
    bl = blacklist or []
    dec = packet.get("_decoded") or decode_packet(packet.get("raw_data", "") or "")
    payload_dec = dec.get("decoded") or {}
    ptype = dec.get("payload_type", "")
    route = dec.get("route_type") or packet.get("_route_type", "")
    is_direct = route in ("Direct", "TransportDirect")
    is_group = ptype in GROUP_TYPES
    full_path = dec.get("path") or packet.get("_path") or []

    placed: list[tuple[str, str, float, float]] = []
    unplaced: list[str] = []
    # Routing-order coords for relay hops (None = unplaced, produces a dashed segment)
    relay_route: list[tuple[float, float] | None] = []

    def _place(label: str, role: str, coords: tuple[float, float]) -> None:
        """Insert (label, role, lat, lon) into placed, respecting role priority dedup."""
        lat, lon = coords
        for i, (_, r, elat, elon) in enumerate(placed):
            if elat == lat and elon == lon:
                if _ROLE_PRIORITY[role] < _ROLE_PRIORITY[r]:
                    placed[i] = (label, role, lat, lon)
                return
        placed.append((label, role, lat, lon))

    def add_node(
        node_id: str, role: str, coords: tuple[float, float] | None = None
    ) -> None:
        """Resolve and place a non-relay node (source / observer / dest)."""
        if is_blacklisted(node_id, db, bl):
            logger.debug(
                "blacklist: skipping node %s (%s) in map",
                node_id,
                resolve_name(node_id, db),
            )
            return
        label = resolve_name(node_id, db)
        if coords is None:
            # Guard: only look up coords when the hash prefix is unambiguous.
            # A short hash matching multiple DB nodes would place the node at
            # the wrong location; better to leave it unplaced.
            node_id_l = node_id.lower()
            n_candidates = sum(
                1 for key in db.get("nodes", {})
                if key.startswith(node_id_l) or node_id_l.startswith(key[: len(node_id_l)])
            )
            if n_candidates <= 1:
                coords = _lookup_coords(node_id, db, remote_coords)
        if coords is None:
            if label not in unplaced:
                unplaced.append(label)
            return
        _place(label, role, coords)

    def add_relay(label: str, coords: tuple[float, float] | None) -> None:
        """Place a relay hop and record its position in relay_route for gap tracking."""
        relay_route.append(coords)
        if coords is None:
            if label not in unplaced:
                unplaced.append(label)
        else:
            _place(label, "relay", coords)

    # --- Source ---
    src_hash = ""
    if ptype == "Advert":
        pub = payload_dec.get("public_key", "")
        if pub:
            raw_lat = payload_dec.get("lat")
            raw_lon = payload_dec.get("lon")
            coords: tuple[float, float] | None = (
                (float(raw_lat), float(raw_lon))
                if raw_lat is not None and raw_lon is not None
                else None
            )
            add_node(pub, "source", coords)
    else:
        src_hash = payload_dec.get("src_hash", "") or packet.get("_src_hash", "")
        # GroupText/GroupData encrypt sender identity; path[0] is last forwarder, not source
        if not src_hash and full_path and not is_direct and not is_group:
            src_hash = full_path[0]
        if src_hash:
            add_node(src_hash, "source")

    # --- Observer ---
    origin_id = packet.get("origin_id", "")
    if origin_id:
        add_node(origin_id, "observer")

    # --- Relays ---
    # Anchor coords for the LoRa range guard: source and observer placed above.
    _anchors: list[tuple[float, float]] = [
        (lat, lon) for _, r, lat, lon in placed if r in ("source", "observer")
    ]

    if is_group and not is_direct:
        relays = full_path
    else:
        relays = full_path if is_direct else full_path[1:]

    if resolved_hops is not None:
        resolved_map = {rh.raw_hash.lower(): rh for rh in resolved_hops}
        for relay_id in relays:
            rh = resolved_map.get(relay_id.lower())
            if rh is None:
                # Hash not in resolved set — fall back to a guarded DB lookup.
                # This path should be rare; it fires when a relay hash wasn't
                # included in the resolve_path_hops() call.
                if is_blacklisted(relay_id, db, bl):
                    logger.debug(
                        "blacklist: skipping relay hop %s in map", relay_id
                    )
                    continue  # blacklisted → not a gap in the path
                label = resolve_name(relay_id, db)
                # Only place if the short hash matches exactly one DB node —
                # a prefix shared by multiple nodes gives wrong coordinates.
                relay_id_l = relay_id.lower()
                n_candidates = sum(
                    1 for key in db.get("nodes", {})
                    if key.startswith(relay_id_l) or relay_id_l.startswith(key[: len(relay_id_l)])
                )
                if n_candidates == 1:
                    full_relay_key = next(
                        key for key in db.get("nodes", {})
                        if key.startswith(relay_id_l) or relay_id_l.startswith(key[: len(relay_id_l)])
                    )
                    # Only use remote_coords when the DB key is full (64 hex chars).
                    # Partial keys prefix-match worldwide nodes → wrong continent.
                    rc = remote_coords if len(full_relay_key) == 64 else None
                    relay_coords = _lookup_coords(full_relay_key, db, rc)
                else:
                    relay_coords = None
                add_relay(label, _guard_relay_range(relay_coords, _anchors, label, max_relay_dist_km))
                continue

            check_key = rh.resolved_key if rh.resolved_key is not None else relay_id
            if is_blacklisted(check_key, db, bl):
                logger.debug(
                    "blacklist: skipping resolved relay hop %s (%s) in map",
                    check_key,
                    rh.name,
                )
                continue  # blacklisted → not a gap in the path

            label = rh.name
            # Only place relays we can identify with confidence.
            # "unknown" has no full key — a short-hash remote lookup would match
            # worldwide nodes and place the relay on the wrong continent.
            # "ambiguous" coords are unreliable (Tier 2 best-guess only).
            if rh.confidence in ("ambiguous", "unknown"):
                relay_coords = None
            elif rh.lat is not None and rh.lon is not None:
                # unique or geo_selected with known coords
                relay_coords = (rh.lat, rh.lon)
            else:
                # Only use remote_coords when we have the full 64-char key.
                # A partial key (<64 chars) prefix-matches many worldwide nodes
                # and would place the relay on the wrong continent.
                key = rh.resolved_key
                if key and len(key) == 64:
                    relay_coords = _lookup_coords(key, db, remote_coords)
                elif key:
                    relay_coords = _lookup_coords(key, db)
                else:
                    relay_coords = None
            add_relay(label, _guard_relay_range(relay_coords, _anchors, label))
    else:
        for hop in relays:
            if is_blacklisted(hop, db, bl):
                logger.debug("blacklist: skipping relay hop %s in map", hop)
                continue  # blacklisted → not a gap in the path
            label = resolve_name(hop, db)
            # Same guard as the rh is None branch above: only place when
            # the hash is unambiguous (single DB match).
            hop_l = hop.lower()
            n_candidates = sum(
                1 for key in db.get("nodes", {})
                if key.startswith(hop_l) or hop_l.startswith(key[: len(hop_l)])
            )
            if n_candidates == 1:
                full_hop_key = next(
                    key for key in db.get("nodes", {})
                    if key.startswith(hop_l) or hop_l.startswith(key[: len(hop_l)])
                )
                rc = remote_coords if len(full_hop_key) == 64 else None
                relay_coords = _lookup_coords(full_hop_key, db, rc)
            else:
                relay_coords = None
            add_relay(label, _guard_relay_range(relay_coords, _anchors, label))

    # --- Dest ---
    # Path packets use "dst_hash"; all other types use "dest_hash".
    dest_hash = payload_dec.get("dest_hash", "") or payload_dec.get("dst_hash", "")
    if dest_hash:
        add_node(dest_hash, "dest")

    # --- Geo-scoring retry for ambiguous source / dest ---
    # After relays and observer are placed we have geographic anchors.  If
    # source or dest couldn't be placed because their short hash (1–2 bytes)
    # matched multiple DB candidates, try to narrow down using proximity:
    # a node is plausible only if its known coords are within LoRa range of
    # at least one already-placed node.
    _geo_anchors: list[tuple[float, float]] = [(lat, lon) for _, _, lat, lon in placed]
    if _geo_anchors:
        if src_hash and not any(r == "source" for _, r, _, _ in placed):
            resolved = _geo_resolve_hash(src_hash, db, _geo_anchors, remote_coords, max_relay_dist_km)
            if resolved:
                src_key, src_geo_coords = resolved
                _place(resolve_name(src_key, db), "source", src_geo_coords)
                logger.debug("map: source %r placed via geo-scoring at %s", src_key, src_geo_coords)

        if dest_hash and not any(r == "dest" for _, r, _, _ in placed):
            resolved = _geo_resolve_hash(dest_hash, db, _geo_anchors, remote_coords, max_relay_dist_km)
            if resolved:
                dst_key, dst_geo_coords = resolved
                _place(resolve_name(dst_key, db), "dest", dst_geo_coords)
                logger.debug("map: dest %r placed via geo-scoring at %s", dst_key, dst_geo_coords)

    # --- Build path segments: source → relays (with gap flags) → observer ---
    src_coords = next(((lat, lon) for _, r, lat, lon in placed if r == "source"), None)
    obs_coords = next(((lat, lon) for _, r, lat, lon in placed if r == "observer"), None)

    route_order: list[tuple[float, float] | None] = [src_coords]
    route_order.extend(relay_route)
    # Only append observer if it adds a new endpoint (prevents zero-length segment)
    last_placed = next((c for c in reversed(route_order) if c is not None), None)
    if obs_coords is not None and obs_coords != last_placed:
        route_order.append(obs_coords)

    path_segments = _route_order_to_segments(route_order)
    return placed, unplaced, path_segments


# ---------------------------------------------------------------------------
# Tile map rendering
# ---------------------------------------------------------------------------

if _HAS_MAP_LIBS:
    class _CachedStaticMap(StaticMap):
        """StaticMap that caches downloaded tiles to ~/.cache/meshcore_tools/tiles/."""

        def get(self, url, **kwargs):
            _TILE_CACHE.mkdir(parents=True, exist_ok=True)
            key = hashlib.sha1(url.encode()).hexdigest()
            path = _TILE_CACHE / key
            if path.exists():
                return 200, path.read_bytes()
            status, content = super().get(url, **kwargs)
            if status == 200:
                path.write_bytes(content)
            return status, content
else:
    _CachedStaticMap = None


def _boxes_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _segment_crosses_box(
    x1: float, y1: float, x2: float, y2: float,
    box: tuple[int, int, int, int],
) -> bool:
    """Liang-Barsky: True if segment (x1,y1)-(x2,y2) intersects axis-aligned box."""
    bx0, by0, bx1, by1 = box
    dx, dy = x2 - x1, y2 - y1
    ps = (-dx, dx, -dy, dy)
    qs = (x1 - bx0, bx1 - x1, y1 - by0, by1 - y1)
    t0, t1 = 0.0, 1.0
    for pi, qi in zip(ps, qs):
        if pi == 0:
            if qi < 0:
                return False
        elif pi < 0:
            t0 = max(t0, qi / pi)
        else:
            t1 = min(t1, qi / pi)
    return t0 <= t1


def _pick_label_pos(
    draw, font, px: int, py: int, label: str,
    placed_boxes: list[tuple[int, int, int, int]],
    line_segs: list[tuple[float, float, float, float]] | None = None,
    pad: int = 6,
) -> tuple[int, int]:
    """Return (x, y) for the label near marker at (px, py).

    Priority:
      1. Avoids other labels AND path lines.
      2. Avoids other labels only (line overlap tolerated).
      3. Default right position (last resort).
    """
    w = int(draw.textlength(label, font=font))
    M = 20  # margin from marker edge (marker radius ~13 px)
    candidates = [
        (M, -10),               # right (default)
        (M, -50),               # above-right
        (M, 20),                # below-right
        (-(w + M), -10),        # left
        (-(w + M), -50),        # above-left
        (-(w + M), 20),         # below-left
        (-w // 2, -(M + 30)),   # above-centre
        (-w // 2, M + 10),      # below-centre
    ]

    def _make_bbox(x: int, y: int) -> tuple[int, int, int, int]:
        bx0, t, bx1, b = draw.textbbox((x, y), label, font=font)
        return (bx0 - pad, t - pad, bx1 + pad, b + pad)

    best_label_safe: tuple[int, int, tuple[int, int, int, int]] | None = None

    for dx, dy in candidates:
        x, y = px + dx, py + dy
        bbox = _make_bbox(x, y)
        if any(_boxes_overlap(bbox, existing) for existing in placed_boxes):
            continue  # always skip label overlaps
        if line_segs and any(_segment_crosses_box(*seg, bbox) for seg in line_segs):
            if best_label_safe is None:
                best_label_safe = (x, y, bbox)  # keep as fallback
            continue
        # Perfect: no label overlap, no line overlap
        placed_boxes.append(bbox)
        return x, y

    if best_label_safe is not None:
        x, y, bbox = best_label_safe
        placed_boxes.append(bbox)
        return x, y

    # Last resort: default position regardless of overlaps
    x, y = px + M, py - 10
    placed_boxes.append(_make_bbox(x, y))
    return x, y


def _draw_dashed_line(
    draw,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color: str,
    width: int,
    dash: int = 20,
    gap: int = 12,
) -> None:
    """Draw a dashed line from (x1,y1) to (x2,y2) using PIL."""
    length = math.hypot(x2 - x1, y2 - y1)
    if length == 0:
        return
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    pos = 0.0
    drawing = True
    while pos < length:
        end = min(pos + (dash if drawing else gap), length)
        if drawing:
            draw.line(
                [
                    (x1 + ux * pos, y1 + uy * pos),
                    (x1 + ux * end, y1 + uy * end),
                ],
                fill=color,
                width=width,
            )
        pos = end
        drawing = not drawing


def _render_tile_map(
    placed: list[tuple[str, str, float, float]],
    path_segments: list[PathSegment],
    width_px: int = 900,
    height_px: int = 500,
):
    """Fetch OSM tiles, draw path line, render node markers, and label them.

    Solid segments connect consecutive placed nodes.
    Dashed segments span gaps where one or more hops had no coordinates.
    """
    from PIL import ImageDraw, ImageFont
    from staticmap.staticmap import _lat_to_y, _lon_to_x

    _font_candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    font = next(
        (ImageFont.truetype(p, 38) for p in _font_candidates if Path(p).exists()),
        ImageFont.load_default(size=38),
    )

    assert _CachedStaticMap is not None  # only reachable when _HAS_MAP_LIBS is True
    m = _CachedStaticMap(width_px, height_px)

    # Add solid path segments via staticmap (rendered beneath markers)
    for (lat1, lon1), (lat2, lon2), is_solid in path_segments:
        if is_solid:
            pts = [(lon1, lat1), (lon2, lat2)]
            m.add_line(Line(pts, "#000000", 8))
            m.add_line(Line(pts, "#ffffff", 4))

    # Markers: larger for visibility
    for _label, role, lat, lon in placed:
        hex_color, _ = _ROLE_COLORS.get(role, ("#ffffff", "white"))
        m.add_marker(CircleMarker((lon, lat), "#000000", 26))  # black border
        m.add_marker(CircleMarker((lon, lat), hex_color, 20))  # colored fill

    image = m.render()
    draw = ImageDraw.Draw(image)

    # Convert all segment endpoints to pixel coords (zoom is fixed after render())
    def _to_px(lat: float, lon: float) -> tuple[float, float]:
        return (
            m._x_to_px(_lon_to_x(lon, m.zoom)),
            m._y_to_px(_lat_to_y(lat, m.zoom)),
        )

    # Draw dashed segments via PIL (appears on top of markers — acceptable for gaps)
    for (lat1, lon1), (lat2, lon2), is_solid in path_segments:
        if not is_solid:
            x1, y1 = _to_px(lat1, lon1)
            x2, y2 = _to_px(lat2, lon2)
            _draw_dashed_line(draw, x1, y1, x2, y2, "#000000", 8)
            _draw_dashed_line(draw, x1, y1, x2, y2, "#ffffff", 4)

    # Build pixel-space line segments for label collision avoidance (all segments)
    line_segs: list[tuple[float, float, float, float]] = []
    for (lat1, lon1), (lat2, lon2), _ in path_segments:
        x1, y1 = _to_px(lat1, lon1)
        x2, y2 = _to_px(lat2, lon2)
        line_segs.append((x1, y1, x2, y2))

    placed_label_boxes: list[tuple[int, int, int, int]] = []
    for label, role, lat, lon in placed:
        px_x, px_y = _to_px(lat, lon)
        lx, ly = _pick_label_pos(
            draw, font, int(px_x), int(px_y), label, placed_label_boxes, line_segs
        )
        draw.text((lx, ly), label, fill="#000000", font=font)

    return image


def _legend() -> str:
    return "  ".join(
        f"[{rich_color}]●[/{rich_color}] {role.capitalize()}"
        for role, (_, rich_color) in _ROLE_COLORS.items()
    )


def _build_footer(placed: list[tuple[str, str, float, float]], unplaced: list[str]) -> str:
    """Build the footer markup string from placed/unplaced node lists."""
    role_summary = ", ".join(
        f"{r}:{sum(1 for _, role, _, _ in placed if role == r)}"
        for r in ("source", "relay", "observer", "dest")
        if any(role == r for _, role, _, _ in placed)
    )
    legend = _legend()
    if role_summary:
        legend += f"  [dim]({role_summary})[/dim]"
    lines = [legend]
    if unplaced:
        _MAX_NAMES = 5
        if len(unplaced) <= _MAX_NAMES:
            names_str = ", ".join(unplaced)
        else:
            names_str = ", ".join(unplaced[:_MAX_NAMES]) + f" +{len(unplaced) - _MAX_NAMES} more"
        lines.append(f"[dim]No coords: {names_str}[/dim]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MapSidePanel widget
# ---------------------------------------------------------------------------

class MapSidePanel(Vertical):
    """Map panel widget for embedding as a side panel in the main monitor.

    Call load_packet(packets, index, db) to render the map for a given packet.
    """

    DEFAULT_CSS = """
    MapSidePanel {
        height: 1fr;
    }
    MapSidePanel #map_side_header {
        height: auto;
        padding: 0 1;
        color: $text-muted;
    }
    MapSidePanel #map_side_body {
        height: 1fr;
        overflow: hidden hidden;
    }
    MapSidePanel #map_side_footer {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._map_widget = None

    def compose(self) -> ComposeResult:
        yield Static("", id="map_side_header", markup=True)
        yield Container(id="map_side_body")
        yield Static("", id="map_side_footer", markup=True)

    def clear(self) -> None:
        """Clear the side panel content."""
        self.query_one("#map_side_header", Static).update("")
        self.query_one("#map_side_footer", Static).update("")
        if self._map_widget is not None:
            self._map_widget.remove()
            self._map_widget = None

    def load_packet(
        self,
        packets: list[dict],
        index: int,
        db: dict,
        blacklist: list[str] | None = None,
    ) -> None:
        """Render the map for packets[index]."""
        p = packets[index]
        dec = p.get("_decoded") or {}
        payload_dec = dec.get("decoded") or {}
        full_path = dec.get("path") or p.get("_path") or []
        src_hash = payload_dec.get("src_hash", "") or p.get("_src_hash", "")
        observer_id = p.get("origin_id", "")
        resolved = resolve_path_hops(
            full_path,
            db,
            blacklist=blacklist,
            source_hash=src_hash or None,
            observer_id=observer_id or None,
        )

        # Quick initial pass (no remote fetch) to populate the footer immediately
        placed, unplaced, _ = collect_map_nodes(p, db, blacklist, resolved_hops=resolved)

        self.query_one("#map_side_header", Static).update(
            f"[dim]Packet {index + 1}/{len(packets)}[/dim]"
        )
        self.query_one("#map_side_footer", Static).update(
            _build_footer(placed, unplaced)
        )

        if self._map_widget is not None:
            self._map_widget.remove()
            self._map_widget = None

        map_body = self.query_one("#map_side_body", Container)

        if not _HAS_MAP_LIBS:
            w = Static(
                "[dim]Map requires: pip install 'meshcore-tools[map]'[/dim]",
                markup=True,
            )
            map_body.mount(w)
            self._map_widget = w
        else:
            w = Static("[dim]Fetching map tiles…[/dim]", markup=True)
            map_body.mount(w)
            self._map_widget = w
            self.call_after_refresh(
                self._start_fetch, p, db, blacklist or [], resolved
            )

    def _start_fetch(
        self,
        packet: dict,
        db: dict,
        blacklist: list[str],
        resolved_hops: list["ResolvedHop"],
    ) -> None:
        map_body = self.query_one("#map_side_body", Container)
        self._fetch_tiles(
            packet, db, blacklist, resolved_hops,
            map_body.size.width, map_body.size.height,
        )

    @work(thread=True, exclusive=True)
    def _fetch_tiles(
        self,
        packet: dict,
        db: dict,
        blacklist: list[str],
        resolved_hops: list["ResolvedHop"],
        w_cells: int,
        h_cells: int,
    ) -> None:
        remote = _ensure_remote_coords()
        placed, unplaced, path_segments = collect_map_nodes(
            packet, db, blacklist, resolved_hops=resolved_hops, remote_coords=remote
        )
        # Update footer if remote lookup moved nodes from unplaced → placed
        self.app.call_from_thread(
            self._update_footer, placed, unplaced
        )
        if not placed:
            self.app.call_from_thread(
                self._show_error,
                "[dim]No coordinates available for this packet.[/dim]",
            )
            return
        cell = _get_cell_size()
        width_px = max(w_cells * cell.width, 400)
        height_px = max(h_cells * cell.height, 300)
        try:
            pil_image = _render_tile_map(placed, path_segments, width_px, height_px)
            self.app.call_from_thread(self._show_tile_image, pil_image)
        except Exception as e:
            self.app.call_from_thread(
                self._show_error,
                f"[red]Map error:[/red] {markup_escape(str(e))}",
            )

    def _update_footer(
        self,
        placed: list[tuple[str, str, float, float]],
        unplaced: list[str],
    ) -> None:
        self.query_one("#map_side_footer", Static).update(
            _build_footer(placed, unplaced)
        )

    def _show_tile_image(self, pil_image) -> None:
        if self._map_widget is not None:
            self._map_widget.remove()
        img = TileImage(pil_image)
        self.query_one("#map_side_body", Container).mount(img)
        self._map_widget = img

    def _show_error(self, text: str) -> None:
        if self._map_widget is not None:
            self._map_widget.remove()
        w = Static(text, markup=True)
        self.query_one("#map_side_body", Container).mount(w)
        self._map_widget = w


# ---------------------------------------------------------------------------
# PacketMapScreen modal
# ---------------------------------------------------------------------------

class PacketMapScreen(ModalScreen):
    """OSM tile map view of nodes involved in a packet, with up/down navigation.

    Requires optional dependencies: pip install 'meshcore-tools[map]'
    """

    DEFAULT_CSS = """
    PacketMapScreen {
        align: center middle;
    }
    #map_outer {
        width: 84;
        height: 46;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    #map_header {
        height: auto;
    }
    #map_body {
        height: 1fr;
        overflow: hidden hidden;
    }
    #map_footer {
        height: auto;
    }
    """

    BINDINGS = [
        Binding("escape,q", "dismiss", "Close"),
        Binding("up,k", "prev", "Previous"),
        Binding("down,j", "next", "Next"),
    ]

    def __init__(
        self,
        packets: list[dict],
        index: int,
        db: dict,
        blacklist: list[str] | None = None,
    ):
        super().__init__()
        self._packets = packets
        self._index = index
        self._db = db
        self._blacklist: list[str] = blacklist or []
        self._map_widget = None

    def compose(self) -> ComposeResult:
        with Vertical(id="map_outer"):
            yield Static("", id="map_header", markup=True)
            yield Container(id="map_body")
            yield Static("", id="map_footer", markup=True)

    def on_mount(self) -> None:
        # Delay until after first layout so map_body.size is known
        self.call_after_refresh(self._refresh_map)

    def _refresh_map(self) -> None:
        p = self._packets[self._index]
        n = len(self._packets)
        dec = p.get("_decoded") or {}
        payload_dec = dec.get("decoded") or {}
        full_path = dec.get("path") or p.get("_path") or []
        src_hash = payload_dec.get("src_hash", "") or p.get("_src_hash", "")
        observer_id = p.get("origin_id", "")
        resolved = resolve_path_hops(
            full_path,
            self._db,
            blacklist=self._blacklist,
            source_hash=src_hash or None,
            observer_id=observer_id or None,
        )

        # Quick initial pass (no remote fetch) to populate the footer immediately
        placed, unplaced, _ = collect_map_nodes(
            p, self._db, self._blacklist, resolved_hops=resolved
        )

        self.query_one("#map_header", Static).update(
            f"[dim]({self._index + 1}/{n}  ↑↓ navigate  q/Esc close)[/dim]"
        )
        self.query_one("#map_footer", Static).update(
            _build_footer(placed, unplaced)
        )

        if self._map_widget is not None:
            self._map_widget.remove()
            self._map_widget = None

        map_body = self.query_one("#map_body", Container)

        if not _HAS_MAP_LIBS:
            w = Static(
                "[dim]Map feature requires optional dependencies.[/dim]\n"
                "Install with: [bold]pip install 'meshcore-tools[map]'[/bold]",
                markup=True,
            )
            map_body.mount(w)
            self._map_widget = w
        else:
            w = Static("[dim]Fetching map tiles…[/dim]", markup=True)
            map_body.mount(w)
            self._map_widget = w
            self._fetch_tile_map(
                p, self._db, self._blacklist, resolved,
                map_body.size.width, map_body.size.height,
            )

        self.app.query_one("#packets", DataTable).move_cursor(row=self._index)
        self.set_focus(None)

    @work(thread=True, exclusive=True)
    def _fetch_tile_map(
        self,
        packet: dict,
        db: dict,
        blacklist: list[str],
        resolved_hops: list["ResolvedHop"],
        w_cells: int,
        h_cells: int,
    ) -> None:
        remote = _ensure_remote_coords()
        placed, unplaced, path_segments = collect_map_nodes(
            packet, db, blacklist, resolved_hops=resolved_hops, remote_coords=remote
        )
        # Update footer if remote lookup moved nodes from unplaced → placed
        self.app.call_from_thread(self._update_footer, placed, unplaced)
        if not placed:
            self.app.call_from_thread(
                self._show_error,
                "[dim]No coordinates available for any node in this packet.[/dim]",
            )
            return
        cell = _get_cell_size()
        width_px = max(w_cells * cell.width, 400)
        height_px = max(h_cells * cell.height, 300)
        try:
            pil_image = _render_tile_map(placed, path_segments, width_px, height_px)
            self.app.call_from_thread(self._show_tile_image, pil_image)
        except Exception as e:
            self.app.call_from_thread(
                self._show_error,
                f"[red]Failed to fetch map tiles:[/red] {markup_escape(str(e))}",
            )

    def _update_footer(
        self,
        placed: list[tuple[str, str, float, float]],
        unplaced: list[str],
    ) -> None:
        self.query_one("#map_footer", Static).update(_build_footer(placed, unplaced))

    def _show_tile_image(self, pil_image) -> None:
        if self._map_widget is not None:
            self._map_widget.remove()
        img = TileImage(pil_image)
        self.query_one("#map_body", Container).mount(img)
        self._map_widget = img
        self.set_focus(None)

    def _show_error(self, text: str) -> None:
        if self._map_widget is not None:
            self._map_widget.remove()
        w = Static(text, markup=True)
        self.query_one("#map_body", Container).mount(w)
        self._map_widget = w
        self.set_focus(None)

    def key_escape(self) -> None:
        self.dismiss()

    def key_q(self) -> None:
        self.dismiss()

    def action_prev(self) -> None:
        if self._index > 0:
            self._index -= 1
            self._refresh_map()

    def action_next(self) -> None:
        if self._index < len(self._packets) - 1:
            self._index += 1
            self._refresh_map()
