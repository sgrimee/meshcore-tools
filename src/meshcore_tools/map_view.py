"""Tile map view of nodes involved in a packet.

Requires optional dependencies:
    pip install "meshcore-tools[map]"   # textual-image, staticmap, Pillow
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from rich.markup import escape as markup_escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from meshcore_tools.db import resolve_name
from meshcore_tools.decoder import GROUP_TYPES, decode_packet

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


def _lookup_coords(node_id: str, db: dict) -> tuple[float, float] | None:
    """Return (lat, lon) for the first db entry matching node_id as a key prefix."""
    node_id = node_id.lower()
    for key, entry in db.get("nodes", {}).items():
        if key.startswith(node_id) or node_id.startswith(key[: len(node_id)]):
            lat = entry.get("lat")
            lon = entry.get("lon")
            if lat is not None and lon is not None:
                return (float(lat), float(lon))
    return None


def collect_map_nodes(
    packet: dict, db: dict
) -> tuple[list[tuple[str, str, float, float]], list[str], list[tuple[float, float]]]:
    """Collect nodes involved in a packet with their coordinates.

    Returns:
        placed:      list of (label, role, lat, lon)
        unplaced:    list of labels for nodes without known coordinates
        path_coords: (lat, lon) pairs in routing order (source→relays→observer)
                     for drawing the path line
    """
    dec = packet.get("_decoded") or decode_packet(packet.get("raw_data", "") or "")
    payload_dec = dec.get("decoded") or {}
    ptype = dec.get("payload_type", "")
    route = dec.get("route_type") or packet.get("_route_type", "")
    is_direct = route in ("Direct", "TransportDirect")
    is_group = ptype in GROUP_TYPES
    full_path = dec.get("path") or packet.get("_path") or []

    placed: list[tuple[str, str, float, float]] = []
    unplaced: list[str] = []

    def add_node(
        node_id: str, role: str, coords: tuple[float, float] | None = None
    ) -> None:
        label = resolve_name(node_id, db)
        if coords is None:
            coords = _lookup_coords(node_id, db)
        if coords is None:
            if label not in unplaced:
                unplaced.append(label)
            return
        lat, lon = coords
        for i, (_, r, elat, elon) in enumerate(placed):
            if elat == lat and elon == lon:
                if _ROLE_PRIORITY[role] < _ROLE_PRIORITY[r]:
                    placed[i] = (label, role, lat, lon)
                return
        placed.append((label, role, lat, lon))

    if ptype == "Advert":
        pub = payload_dec.get("public_key", "")
        if pub:
            raw_lat = payload_dec.get("lat")
            raw_lon = payload_dec.get("lon")
            coords = (
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

    origin_id = packet.get("origin_id", "")
    if origin_id:
        add_node(origin_id, "observer")

    # For group types, all path entries are forwarders (source is encrypted)
    if is_group and not is_direct:
        relays = full_path
    else:
        relays = full_path if is_direct else full_path[1:]
    for hop in relays:
        add_node(hop, "relay")

    dest_hash = payload_dec.get("dest_hash", "")
    if dest_hash:
        add_node(dest_hash, "dest")

    # Build routing-order path for line drawing: source → relays → observer
    src = next(((lat, lon) for _, r, lat, lon in placed if r == "source"), None)
    relay_coords = [(lat, lon) for _, r, lat, lon in placed if r == "relay"]
    obs = next(((lat, lon) for _, r, lat, lon in placed if r == "observer"), None)
    path_coords: list[tuple[float, float]] = []
    if src:
        path_coords.append(src)
    path_coords.extend(relay_coords)
    if obs and obs not in path_coords:
        path_coords.append(obs)

    return placed, unplaced, path_coords


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


def _render_tile_map(
    placed: list[tuple[str, str, float, float]],
    path_coords: list[tuple[float, float]],
    width_px: int = 900,
    height_px: int = 500,
):
    """Fetch OSM tiles, draw path line, render node markers, and label them."""
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

    # Path line: dark outline + white core, drawn before markers so markers sit on top
    if len(path_coords) >= 2:
        pts = [(lon, lat) for lat, lon in path_coords]  # staticmap uses (lon, lat)
        m.add_line(Line(pts, "#000000", 8))
        m.add_line(Line(pts, "#ffffff", 4))

    # Markers: larger for visibility
    for _label, role, lat, lon in placed:
        hex_color, _ = _ROLE_COLORS.get(role, ("#ffffff", "white"))
        m.add_marker(CircleMarker((lon, lat), "#000000", 26))  # black border
        m.add_marker(CircleMarker((lon, lat), hex_color, 20))  # colored fill

    image = m.render()
    draw = ImageDraw.Draw(image)

    # Build path line segments in pixel coords (zoom is fixed after render())
    line_segs: list[tuple[float, float, float, float]] = []
    if len(path_coords) >= 2:
        pts_px = [
            (m._x_to_px(_lon_to_x(lon, m.zoom)), m._y_to_px(_lat_to_y(lat, m.zoom)))
            for lat, lon in path_coords
        ]
        for i in range(len(pts_px) - 1):
            ax, ay = pts_px[i]
            bx, by = pts_px[i + 1]
            line_segs.append((ax, ay, bx, by))

    placed_label_boxes: list[tuple[int, int, int, int]] = []

    for label, role, lat, lon in placed:
        hex_color, _ = _ROLE_COLORS.get(role, ("#ffffff", "white"))
        px = m._x_to_px(_lon_to_x(lon, m.zoom))
        py = m._y_to_px(_lat_to_y(lat, m.zoom))
        lx, ly = _pick_label_pos(draw, font, px, py, label, placed_label_boxes, line_segs)
        draw.text((lx, ly), label, fill="#000000", font=font)

    return image


def _legend() -> str:
    return "  ".join(
        f"[{rich_color}]●[/{rich_color}] {role.capitalize()}"
        for role, (_, rich_color) in _ROLE_COLORS.items()
    )


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

    def load_packet(self, packets: list[dict], index: int, db: dict) -> None:
        """Render the map for packets[index]."""
        p = packets[index]
        placed, unplaced, path_coords = collect_map_nodes(p, db)

        self.query_one("#map_side_header", Static).update(
            f"[dim]Packet {index + 1}/{len(packets)}[/dim]"
        )
        footer_lines = [_legend()]
        if unplaced:
            footer_lines.append("[dim]No coords:[/dim] " + ", ".join(unplaced))
        self.query_one("#map_side_footer", Static).update("\n".join(footer_lines))

        if self._map_widget is not None:
            self._map_widget.remove()
            self._map_widget = None

        map_body = self.query_one("#map_side_body", Container)

        if not _HAS_MAP_LIBS:
            w = Static(
                "[dim]Map requires: pip install 'meshcore-tools[map]'[/dim]", markup=True
            )
            map_body.mount(w)
            self._map_widget = w
        elif not placed:
            w = Static(
                "[dim]No coordinates available for this packet.[/dim]", markup=True
            )
            map_body.mount(w)
            self._map_widget = w
        else:
            w = Static("[dim]Fetching map tiles…[/dim]", markup=True)
            map_body.mount(w)
            self._map_widget = w
            self._fetch_tiles(placed, path_coords, map_body.size.width, map_body.size.height)

    @work(thread=True, exclusive=True)
    def _fetch_tiles(
        self,
        placed: list[tuple[str, str, float, float]],
        path_coords: list[tuple[float, float]],
        w_cells: int,
        h_cells: int,
    ) -> None:
        cell = _get_cell_size()
        cw, ch = cell.width, cell.height
        width_px = max(w_cells * cw, 400)
        height_px = max(h_cells * ch, 300)
        try:
            pil_image = _render_tile_map(placed, path_coords, width_px, height_px)
            self.app.call_from_thread(self._show_tile_image, pil_image)
        except Exception as e:
            self.app.call_from_thread(
                self._show_error,
                f"[red]Map error:[/red] {markup_escape(str(e))}",
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

    def __init__(self, packets: list[dict], index: int, db: dict):
        super().__init__()
        self._packets = packets
        self._index = index
        self._db = db
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
        placed, unplaced, path_coords = collect_map_nodes(p, self._db)

        self.query_one("#map_header", Static).update(
            f"[dim]({self._index + 1}/{n}  ↑↓ navigate  q/Esc close)[/dim]"
        )

        footer_lines = [_legend()]
        if unplaced:
            footer_lines.append("[dim]No coords:[/dim] " + ", ".join(unplaced))
        self.query_one("#map_footer", Static).update("\n".join(footer_lines))

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
        elif not placed:
            w = Static(
                "[dim]No coordinates available for any node in this packet.[/dim]",
                markup=True,
            )
            map_body.mount(w)
            self._map_widget = w
        else:
            w = Static("[dim]Fetching map tiles…[/dim]", markup=True)
            map_body.mount(w)
            self._map_widget = w
            self._fetch_tile_map(placed, path_coords, map_body.size.width, map_body.size.height)

        self.app.query_one("#packets", DataTable).move_cursor(row=self._index)
        self.set_focus(None)

    @work(thread=True, exclusive=True)
    def _fetch_tile_map(
        self,
        placed: list[tuple[str, str, float, float]],
        path_coords: list[tuple[float, float]],
        w_cells: int,
        h_cells: int,
    ) -> None:
        cell = _get_cell_size()
        cw, ch = cell.width, cell.height
        width_px = max(w_cells * cw, 400)
        height_px = max(h_cells * ch, 300)
        try:
            pil_image = _render_tile_map(placed, path_coords, width_px, height_px)
            self.app.call_from_thread(self._show_tile_image, pil_image)
        except Exception as e:
            self.app.call_from_thread(
                self._show_error,
                f"[red]Failed to fetch map tiles:[/red] {markup_escape(str(e))}",
            )

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
