"""Live packet monitoring TUI using Textual."""

from __future__ import annotations

import textwrap
import time
from datetime import datetime, timezone

from rich.markup import escape as markup_escape
from rich.text import Text

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.containers import Container, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Input, Label, Static, TabPane
from textual.worker import get_current_worker

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meshcore_tools.providers import PacketProvider

from meshcore_tools.db import is_input_node, learn_from_advert, load_db, resolve_name, save_db
from meshcore_tools.decoder import GROUP_TYPES, decode_packet
from meshcore_tools.map_view import MapSidePanel, PacketMapScreen
from meshcore_tools.channels import build_channel_lookup, load_channels, try_decrypt
from meshcore_tools.resize_handle import ResizeHandle

MAX_PACKETS = 500




def format_path(path_list: list, db: dict, resolve: int = 2,
                src_hash: str = "", route_type: str = "",
                hop_size: int = 1, ptype: str = "") -> str:
    """Format: source → relay1 → relay2 → ...

    resolve: 2 = all names, 1 = source name + relay hex, 0 = all hex.
    src_hash: authoritative source (from payload or Advert pubkey).
    route_type: "Direct"/"TransportDirect" means path entries are relays, not source.
    hop_size: bytes per hop — used to trim src_hash display to match relay display width.
    ptype: payload type — GroupText/GroupData have no src_hash by design; path[0] is
           the last forwarder, not the original sender.
    """
    is_direct = route_type in ("Direct", "TransportDirect")
    is_group = ptype in GROUP_TYPES

    def _fmt(display: str, node_id: str) -> str:
        return f"[yellow]{display}[/yellow]" if is_input_node(node_id, db) else display

    # Determine source display (trim src_hash to hop_size for visual consistency)
    if src_hash:
        text = resolve_name(src_hash, db) if resolve >= 1 else _trim_hash(src_hash, hop_size)
        src = _fmt(text, src_hash)
    elif is_group and not is_direct:
        # GroupText/GroupData encrypt sender identity; path[0] is the last forwarder
        src = "[dim]enc[/dim]"
    elif path_list and not is_direct:
        text = resolve_name(path_list[0], db) if resolve >= 1 else path_list[0]
        src = _fmt(text, path_list[0])
    else:
        src = "?"

    # Relays: for Direct all path hops are relays; for Flood skip first (= source).
    # For group types all path entries are forwarders (no reliable source in path).
    if is_group and not is_direct:
        relays = path_list
    else:
        relays = path_list if is_direct else path_list[1:]

    if not relays:
        return src

    if resolve >= 2:
        relay_parts = [_fmt(resolve_name(hop, db), hop) for hop in relays]
    else:
        relay_parts = [_fmt(hop, hop) for hop in relays]

    return " → ".join([src] + relay_parts)


def format_payload_type(pt: str) -> str:
    return (pt or "")[:10]


def fmt_key_prefix(key: str) -> str:
    """Format first 3 bytes of a hex key as 'xx xx xx'."""
    k = key.lower().ljust(6, "_")[:6]
    return f"{k[0:2]} {k[2:4]} {k[4:6]}"


def fmt_ts(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso


def _trim_hash(h: str, hop_size: int) -> str:
    """Trim hash to hop_size bytes for display (keeps full value for resolution)."""
    return h[:hop_size * 2]


def _fmt_hash(h: str, db: dict, hop_size: int = 1) -> str:
    """Format a hash with its resolved name. Display truncated to hop_size bytes."""
    display = _trim_hash(h, hop_size)
    name = resolve_name(h, db)
    if is_input_node(h, db):
        return f"[dim yellow]{display}[/dim yellow]  [yellow]{name}[/yellow]"
    return f"[dim]{display}[/dim]  {name}"


def _build_detail_text(packet: dict, db: dict) -> str:
    p = packet
    dec = p.get("_decoded") or decode_packet(p.get("raw_data", "") or "")

    observer_name = p.get("origin") or resolve_name(p.get("origin_id", ""), db)
    route = dec.get("route_type") or p.get("route_type", "-")
    ptype = dec.get("payload_type") or p.get("payload_type", "-")
    pver = dec.get("payload_version")
    pver_str = f"  v{pver}" if pver is not None else ""

    lines = [
        "[bold]Packet detail[/bold]",
        "",
        f"[dim]Observer:[/dim]   {observer_name}",
        f"[dim]Origin ID:[/dim]  {p.get('origin_id', '-')}",
        f"[dim]Heard at:[/dim]   {fmt_ts(p.get('heard_at', ''))}",
        f"[dim]SNR:[/dim]        {p.get('snr', '-')}  "
        f"[dim]RSSI:[/dim] {p.get('rssi', '-')}  "
        f"[dim]Score:[/dim] {p.get('score', '-')}",
        "",
        f"[dim]Route:[/dim]      {route}",
        f"[dim]Type:[/dim]       {ptype}{pver_str}",
    ]

    # --- Source / Relays / Destination ---
    lines.append("")
    full_path = dec.get("path") or p.get("_path") or []
    hop_size = dec.get("path_hop_size", 1)
    payload_dec = dec.get("decoded") or {}

    is_direct = route in ("Direct", "TransportDirect")
    is_group = ptype in GROUP_TYPES

    # Authoritative source: payload src_hash (all encrypted types) or Advert public_key
    src_hash = payload_dec.get("src_hash", "") or p.get("_src_hash", "")
    advert_pubkey = payload_dec.get("public_key", "") if ptype == "Advert" else ""

    if advert_pubkey:
        lines.append(f"[dim]Source:[/dim]     [dim]{_trim_hash(advert_pubkey, hop_size)}[/dim]  "
                     f"{resolve_name(advert_pubkey, db)}")
    elif src_hash:
        lines.append(f"[dim]Source:[/dim]     {_fmt_hash(src_hash, db, hop_size)}")
    elif is_group:
        # GroupText/GroupData encrypt sender identity; show if decrypted
        decrypted = p.get("_decrypted")
        if decrypted and decrypted.get("sender"):
            lines.append(f"[dim]Source:[/dim]     {markup_escape(decrypted['sender'])}")
        else:
            lines.append("[dim]Source:[/dim]     [dim]encrypted[/dim]")
    elif full_path and not is_direct:
        lines.append(f"[dim]Source:[/dim]     {_fmt_hash(full_path[0], db, hop_size)}")
    else:
        lines.append("[dim]Source:[/dim]     unknown")

    # Relays: for Direct routing all path hops are relays; for Flood skip path[0] (=source).
    # For group types path[0] is the last forwarder (sender identity is encrypted),
    # so show it as "Forwarder" and treat the remaining hops as relays.
    if is_group and not is_direct:
        forwarder = full_path[0] if full_path else None
        relays = full_path[1:]
        if forwarder:
            lines.append(f"[dim]Forwarder:[/dim]  {_fmt_hash(forwarder, db, hop_size)}")
    else:
        relays = full_path if is_direct else full_path[1:]
    lines.append(f"[dim]Path:[/dim]       {hop_size}-byte addresses")
    if relays:
        lines.append("[dim]Relays:[/dim]")
        for hop in relays:
            lines.append(f"  {_fmt_hash(hop, db, hop_size)}")
    else:
        lines.append("[dim]Relays:[/dim]     none")

    dest_hash = payload_dec.get("dest_hash", "")
    if dest_hash:
        lines.append(f"[dim]Dest:[/dim]       {_fmt_hash(dest_hash, db, hop_size)}")

    # --- Decoded payload ---
    lines.append("")
    if dec.get("error"):
        lines.append(f"[dim]Decode error:[/dim] {dec['error']}")
    elif payload_dec:
        lines += _fmt_payload(ptype, payload_dec, db, p)
    elif dec.get("payload_hex"):
        lines.append(f"[dim]Payload:[/dim]    {dec['payload_hex'][:64]}"
                     + ("…" if len(dec.get("payload_hex", "")) > 64 else ""))

    raw_data = p.get("raw_data", "")
    if raw_data:
        lines.append("")
        raw_display = raw_data
        if full_path or advert_pubkey:
            is_transport = route in ("TransportFlood", "TransportDirect")
            first_hop_byte = 6 if is_transport else 2
            start = first_hop_byte * 2
            end = start + hop_size * 2
            if len(raw_data) >= end:
                raw_display = (
                    raw_data[:start]
                    + f"[bold yellow]{raw_data[start:end]}[/bold yellow]"
                    + raw_data[end:]
                )
        lines.append(f"[dim]Raw:[/dim]        {raw_display}")

    regions = p.get("regions") or []
    if regions:
        lines.append("")
        lines.append(f"[dim]Regions:[/dim]    {', '.join(regions)}")

    lines += [
        "",
        f"[dim]ID:[/dim]         {p.get('id', '-')}",
        f"[dim]Created:[/dim]    {fmt_ts(p.get('created_at', ''))}",
    ]
    return "\n".join(lines)


def _fmt_payload(ptype: str, d: dict, db: dict, packet: dict | None = None) -> list[str]:
    """Format decoded payload fields for the detail view."""
    lines: list[str] = []

    if ptype == "Advert":
        if d.get("name"):
            lines.append(f"[dim]Name:[/dim]       {d['name']}")
        lines.append(f"[dim]Role:[/dim]       {d.get('role', '-')}")
        if "lat" in d and "lon" in d:
            lines.append(f"[dim]Location:[/dim]   {d['lat']}, {d['lon']}")
        lines.append(f"[dim]Timestamp:[/dim]  {d.get('timestamp', '-')}")
        lines.append(f"[dim]Public key:[/dim] {d.get('public_key', '-')}")
        lines.append(f"[dim]Flags:[/dim]      {d.get('flags', '-')}")

    elif ptype in ("Request", "Response", "TextMessage", "AnonRequest"):
        lines.append(f"[dim]MAC:[/dim]        {d.get('cipher_mac', '-')}")
        lines.append(f"[dim]Content:[/dim]    encrypted ({d.get('ciphertext_len', 0)} bytes)")

    elif ptype in GROUP_TYPES:
        decrypted = (packet or {}).get("_decrypted")
        if decrypted:
            lines.append(f"[dim]Channel:[/dim]    {markup_escape(decrypted['channel'])}")
            lines.append(f"[dim]Message:[/dim]    {markup_escape(decrypted['message'])}")
        else:
            lines.append(f"[dim]Channel:[/dim]    {d.get('channel_hash', '-')}")
            lines.append(f"[dim]MAC:[/dim]        {d.get('cipher_mac', '-')}")
            lines.append(f"[dim]Content:[/dim]    encrypted ({d.get('ciphertext_len', 0)} bytes)")

    elif ptype == "Trace":
        lines.append(f"[dim]Trace tag:[/dim]  {d.get('trace_tag', '-')}")
        lines.append(f"[dim]Auth code:[/dim]  {d.get('auth_code', '-')}")
        snrs = d.get("hop_snrs_db", [])
        if snrs:
            lines.append(f"[dim]Hop SNRs:[/dim]   {', '.join(str(s) for s in snrs)} dB")

    elif ptype == "Ack":
        lines.append(f"[dim]Payload:[/dim]    {d.get('raw', '-')} ({d.get('length', 0)} bytes)")

    elif ptype == "Path":
        if d.get("dst_hash"):
            lines.append(f"[dim]Dest hash:[/dim]  {_fmt_hash(d['dst_hash'], db)}")
        extra = d.get("extra_hops", [])
        if extra:
            lines.append(f"[dim]Extra hops:[/dim] {', '.join(extra)}")

    elif d.get("error"):
        lines.append(f"[dim]Error:[/dim]      {d['error']}")
    else:
        for k, v in d.items():
            lines.append(f"  {k}: {v}")

    return lines


class FilterScreen(ModalScreen[dict]):
    """Modal dialog for filtering packets by multiple criteria."""

    DEFAULT_CSS = """
    FilterScreen {
        align: center middle;
    }
    FilterScreen > Static {
        width: 54;
        padding: 1 2 0 2;
        background: $surface;
    }
    FilterScreen > #title {
        padding: 1 2 0 2;
        background: $surface;
        text-style: bold;
    }
    FilterScreen > #hint {
        padding: 0 2 1 2;
        background: $surface;
        color: $text-muted;
        text-style: italic;
    }
    FilterScreen > Input {
        width: 54;
        border: solid $accent;
        background: $surface;
        padding: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "clear_all", "Clear all")]

    def __init__(self, filters: dict):
        super().__init__()
        self._pkt_filters = filters

    def compose(self) -> ComposeResult:
        yield Static("Packet Filters  (name or hex address)", id="title", markup=False)
        yield Static("Observer:", markup=False)
        yield Input(value=self._pkt_filters.get("observer", ""), placeholder="e.g.  gw-home  or  ab cd ef", id="observer")
        yield Static("Node in path (source or relay):", markup=False)
        yield Input(value=self._pkt_filters.get("path_node", ""), placeholder="e.g.  relay  or  f4  or  ab cd", id="path_node")
        yield Static("↵ apply · Esc clear all · Tab next field", id="hint", markup=False)

    def on_mount(self) -> None:
        self.query_one("#observer", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._apply()

    def _apply(self) -> None:
        self.dismiss({
            "observer": self.query_one("#observer", Input).value.strip(),
            "path_node": self.query_one("#path_node", Input).value.strip(),
        })

    def action_clear_all(self) -> None:
        self.dismiss({"observer": "", "path_node": ""})


class PacketDetailScreen(ModalScreen):
    """Full-packet detail view with up/down navigation."""

    DEFAULT_CSS = """
    PacketDetailScreen {
        align: center middle;
    }
    PacketDetailScreen > Static {
        width: 72;
        height: auto;
        max-height: 40;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        Binding("escape,q", "dismiss", "Close"),
        Binding("up,k", "prev", "Previous"),
        Binding("down,j", "next", "Next"),
        Binding("M", "open_map", "Map popup"),
    ]

    def __init__(self, packets: list[dict], index: int, db: dict):
        super().__init__()
        self._packets = packets
        self._index = index
        self._db = db

    def compose(self) -> ComposeResult:
        yield Static("", id="content", markup=True)

    def on_mount(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        p = self._packets[self._index]
        n = len(self._packets)
        header = f"[dim]({self._index + 1}/{n}  ↑↓ navigate  shift+m map)[/dim]\n"
        self.query_one("#content", Static).update(
            header + _build_detail_text(p, self._db)
        )
        # Keep the underlying table cursor in sync
        self.app.query_one("#packets", DataTable).move_cursor(row=self._index)

    def action_prev(self) -> None:
        if self._index > 0:
            self._index -= 1
            self._refresh_content()

    def action_next(self) -> None:
        if self._index < len(self._packets) - 1:
            self._index += 1
            self._refresh_content()

    def key_escape(self) -> None:
        self.dismiss()

    def key_q(self) -> None:
        self.dismiss()

    def action_open_map(self) -> None:
        self.app.push_screen(PacketMapScreen(self._packets, self._index, self._db))


class PacketMonitorApp(App):
    """Live MeshCore packet monitor."""

    TITLE = "MeshCore Monitor"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("p", "pause", "Pause/Resume"),
        Binding("f", "filter", "Filter"),
        Binding("d", "toggle_detail_panel", "Detail", key_display="(S-)d"),
        Binding("D", "open_detail", "Detail popup", show=False),
        Binding("m", "toggle_map_panel", "Map", key_display="(S-)m"),
        Binding("M", "open_map", "Map popup", show=False),
        Binding("a", "toggle_follow", "Follow"),
        Binding("b", "toggle_layout", "Layout"),
        Binding("n", "toggle_names", "Names"),
        Binding("w", "toggle_wrap", "Wrap"),
        Binding("c", "clear", "Clear"),
    ]
    CSS = """
    /* === Main layout (right-panel mode, default) === */
    #main_area {
        height: 1fr;
        layout: horizontal;
    }
    DataTable {
        width: 1fr;
        height: 1fr;
    }
    #panel_area {
        display: none;
        layout: vertical;
        width: 60;
        height: 1fr;
        background: $surface;
    }
    #panel_resize {
        display: none;
        width: 1;
        height: 1fr;
        background: $accent 15%;
    }
    #panel_resize:hover {
        background: $accent 50%;
    }
    #detail_side {
        display: none;
        height: 1fr;
        padding: 1 2;
    }
    MapSidePanel {
        display: none;
        height: 1fr;
    }
    /* === Bottom-panel mode === */
    PacketMonitorApp.panels-bottom #main_area {
        layout: vertical;
    }
    PacketMonitorApp.panels-bottom #panel_area {
        layout: horizontal;
        width: 1fr;
        height: 18;
    }
    PacketMonitorApp.panels-bottom #panel_resize {
        width: 1fr;
        height: 1;
    }
    PacketMonitorApp.panels-bottom #detail_side,
    PacketMonitorApp.panels-bottom MapSidePanel {
        width: 1fr;
        height: 1fr;
    }
    /* === Status bar === */
    #status {
        height: 1;
        background: $panel;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        region: str,
        packet_provider: PacketProvider,
        poll_interval: int = 5,
        channels_path: str | None = None,
    ):
        super().__init__()
        self.region = region
        self.poll_interval = poll_interval
        self._packet_provider = packet_provider
        channels = load_channels(channels_path) if channels_path else []
        self._channel_lookup = build_channel_lookup(channels)
        self._db: dict = {"nodes": {}}
        self._seen_ids: set[str] = set()
        self._paused = False
        self._pkt_filters: dict = {"observer": "", "path_node": ""}
        self._all_packets: list[dict] = []
        self._packets_by_id: dict[str, dict] = {}
        self._displayed: list[dict] = []
        self._resolve_path: int = 2  # 2=all names, 1=src name+relay hex, 0=all hex
        self._wrap_path: bool = False
        self._detail_panel_open: bool = False
        self._map_panel_open: bool = False
        self._follow: bool = False
        self._layout_bottom: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="main_area"):
            yield DataTable(id="packets")
            yield ResizeHandle(
                target_getter=lambda: self.query_one("#panel_area"),
                min_size=20,
                max_size=150,
                id="panel_resize",
            )
            with Container(id="panel_area"):
                with VerticalScroll(id="detail_side"):
                    yield Static("", id="detail_content", markup=True)
                yield MapSidePanel(id="map_side")
        yield Label("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._db = load_db()
        table = self.query_one("#packets", DataTable)
        table.add_columns("Time", "Observer", "Type", "SNR", "RSSI", "Src→Relays")
        table.cursor_type = "row"
        self.sub_title = f"region={self.region}  poll={self.poll_interval}s"
        self._set_status(None)
        self._poll_worker()

    @work(thread=True, exclusive=True)
    def _poll_worker(self) -> None:
        worker = get_current_worker()
        while not worker.is_cancelled:
            try:
                packets = self._packet_provider.fetch_packets(self.region, limit=500)
                self.call_from_thread(self._ingest_packets, packets)
            except Exception as e:
                self.call_from_thread(self._set_status, str(e))
            for _ in range(self.poll_interval * 10):
                if worker.is_cancelled:
                    return
                time.sleep(0.1)

    def _ingest_packets(self, packets: list[dict]) -> None:
        region = self.region.upper()
        new = [
            p for p in packets
            if p.get("id") not in self._seen_ids
            and region in [r.upper() for r in (p.get("regions") or [])]
        ]
        if not new:
            self._set_status(None)
            return
        db_dirty = False
        for p in new:
            self._seen_ids.add(p["id"])
            pkt_dec = decode_packet(p.get("raw_data", "") or "")
            p["_path"] = pkt_dec.get("path") or []
            p["_decoded"] = pkt_dec
            decoded_payload = pkt_dec.get("decoded") or {}
            p["_src_hash"] = decoded_payload.get("src_hash", "")
            p["_route_type"] = pkt_dec.get("route_type", "")
            p["_path_hop_size"] = pkt_dec.get("path_hop_size", 1)
            # For Advert packets, learn node identity and use full key as src
            if pkt_dec.get("payload_type") == "Advert" and decoded_payload.get("public_key"):
                pub = decoded_payload["public_key"]
                name = decoded_payload.get("name") or pub[:8]
                role = decoded_payload.get("role", "")
                lat = decoded_payload.get("lat")
                lon = decoded_payload.get("lon")
                if learn_from_advert(self._db, pub, name, role, lat, lon):
                    db_dirty = True
                p["_src_hash"] = pub[:12]
            # For GroupText/GroupData, attempt decryption with configured channels
            if (pkt_dec.get("payload_type") in GROUP_TYPES
                    and self._channel_lookup):
                raw_payload = bytes.fromhex(pkt_dec.get("payload_hex", "") or "")
                if len(raw_payload) >= 3:
                    ch_byte = raw_payload[0]
                    mac = raw_payload[1:3]
                    ciphertext = raw_payload[3:]
                    result = try_decrypt(ch_byte, mac, ciphertext, self._channel_lookup)
                    if result:
                        p["_decrypted"] = result
            self._packets_by_id[p["id"]] = p
        if db_dirty:
            save_db(self._db)
        self._all_packets = (new + self._all_packets)[:MAX_PACKETS]
        visible_ids = {p["id"] for p in self._all_packets}
        self._packets_by_id = {k: v for k, v in self._packets_by_id.items() if k in visible_ids}
        if not self._paused:
            self._rebuild_table()
        self._set_status(None)

    def _node_matches(self, term: str, node_id: str) -> bool:
        """True if term matches the node by name substring or hex address prefix."""
        t = term.lower().replace(" ", "")
        return t in resolve_name(node_id, self._db).lower() or node_id.lower().startswith(t)

    def _packet_matches(self, p: dict) -> bool:
        f = self._pkt_filters
        obs_id = p.get("origin_id", "")
        path_ids = p.get("_path") or []
        src_hash = p.get("_src_hash", "")

        if f["observer"]:
            t = f["observer"].lower()
            origin_name = (p.get("origin") or "").lower()
            if t not in origin_name and not self._node_matches(f["observer"], obs_id):
                return False

        if f["path_node"]:
            obs_id_lower = obs_id.lower()
            def _is_obs(nid: str) -> bool:
                n = nid.lower()
                return obs_id_lower.startswith(n) or n.startswith(obs_id_lower)
            path_and_src = [nid for nid in list(path_ids) + ([src_hash] if src_hash else [])
                            if nid and not _is_obs(nid)]
            if not any(self._node_matches(f["path_node"], nid) for nid in path_and_src):
                return False

        return True

    def _rebuild_table(self) -> None:
        table = self.query_one("#packets", DataTable)
        # Preserve current packet across rebuilds when not following
        pinned_id: str | None = None
        if not self._follow and self._displayed:
            cr = table.cursor_row
            if cr < len(self._displayed):
                pinned_id = self._displayed[cr].get("id")
        table.clear()
        self._displayed = [p for p in self._all_packets if self._packet_matches(p)]
        for p in self._displayed:
            heard = p.get("heard_at", "")
            try:
                dt = datetime.fromisoformat(heard.replace("Z", "+00:00"))
                time_str = dt.astimezone().strftime("%H:%M:%S")
            except Exception:
                time_str = heard[:8]
            node = p.get("origin") or resolve_name(p.get("origin_id", ""), self._db)
            ptype = format_payload_type(p.get("payload_type", ""))
            snr = f"{p['snr']:.1f}" if p.get("snr") is not None else "-"
            rssi = str(p.get("rssi", "-"))
            raw_path = p.get("_path") or []
            # Use decrypted sender name as source display when available
            decrypted = p.get("_decrypted") or {}
            src_display = decrypted.get("sender", "") or p.get("_src_hash", "")
            path = format_path(raw_path, self._db, resolve=self._resolve_path,
                               src_hash=src_display,
                               route_type=p.get("_route_type", ""),
                               hop_size=p.get("_path_hop_size", 1),
                               ptype=p.get("payload_type", ""))
            if self._wrap_path:
                wrap_width = max(20, self.size.width - 58)
                lines = textwrap.wrap(path, width=wrap_width) or [path]
                path_cell = Text.from_markup("\n".join(lines))
                row_height = len(lines)
            else:
                path_cell = Text.from_markup(path)
                row_height = 1
            table.add_row(time_str, node, ptype, snr, rssi, path_cell, height=row_height, key=p["id"])
        # Restore cursor: pin to previous packet (no-follow) or stay at 0 (follow)
        target_row = 0
        if pinned_id:
            for i, p in enumerate(self._displayed):
                if p.get("id") == pinned_id:
                    target_row = i
                    break
        if target_row > 0:
            table.move_cursor(row=target_row)
        # Update open side panels (move_cursor won't fire RowHighlighted when row==0)
        if self._displayed:
            if self._detail_panel_open:
                self._update_detail_side(target_row)
            if self._map_panel_open:
                self._update_map_side(target_row)

    def action_open_detail(self) -> None:
        if not self._displayed:
            return
        row = self.query_one("#packets", DataTable).cursor_row
        self.push_screen(PacketDetailScreen(self._displayed, row, self._db))

    def action_open_map(self) -> None:
        if not self._displayed:
            return
        row = self.query_one("#packets", DataTable).cursor_row
        self.push_screen(PacketMapScreen(self._displayed, row, self._db))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        row = event.cursor_row
        if not self._displayed or row >= len(self._displayed):
            return
        if self._detail_panel_open:
            self._update_detail_side(row)
        if self._map_panel_open:
            self._update_map_side(row)

    def _update_detail_side(self, row: int) -> None:
        if not self._displayed or row >= len(self._displayed):
            return
        p = self._displayed[row]
        self.query_one("#detail_content", Static).update(_build_detail_text(p, self._db))

    def _update_map_side(self, row: int) -> None:
        if not self._displayed or row >= len(self._displayed):
            return
        self.query_one(MapSidePanel).load_packet(self._displayed, row, self._db)

    def _sync_panel_area(self) -> None:
        """Show #panel_area (and its resize handle) iff at least one side panel is open."""
        visible = self._detail_panel_open or self._map_panel_open
        self.query_one("#panel_area").display = visible
        self.query_one("#panel_resize").display = visible

    def action_toggle_detail_panel(self) -> None:
        self._detail_panel_open = not self._detail_panel_open
        self.query_one("#detail_side", VerticalScroll).display = self._detail_panel_open
        self._sync_panel_area()
        if self._detail_panel_open:
            row = self.query_one("#packets", DataTable).cursor_row
            self._update_detail_side(row)

    def action_toggle_map_panel(self) -> None:
        self._map_panel_open = not self._map_panel_open
        self.query_one(MapSidePanel).display = self._map_panel_open
        self._sync_panel_area()
        if self._map_panel_open:
            row = self.query_one("#packets", DataTable).cursor_row
            self._update_map_side(row)

    def action_toggle_follow(self) -> None:
        self._follow = not self._follow
        self._set_status(None)

    def action_toggle_layout(self) -> None:
        self._layout_bottom = not self._layout_bottom
        if self._layout_bottom:
            self.add_class("panels-bottom")
        else:
            self.remove_class("panels-bottom")
        self._set_status(None)

    def action_toggle_names(self) -> None:
        self._resolve_path = (self._resolve_path - 1) % 3
        self._rebuild_table()
        self._set_status(None)

    def action_toggle_wrap(self) -> None:
        self._wrap_path = not self._wrap_path
        self._rebuild_table()
        self._set_status(None)

    def action_clear(self) -> None:
        self._all_packets = []
        self._displayed = []
        self._seen_ids = set()
        self._packets_by_id = {}
        self.query_one("#packets", DataTable).clear()
        self.query_one("#detail_content", Static).update("")
        self.query_one(MapSidePanel).clear()
        self._set_status(None)

    def _set_status(self, error: str | None) -> None:
        state = "[PAUSED]" if self._paused else "[LIVE]"
        parts = []
        if self._pkt_filters["observer"]:
            parts.append(f"obs={markup_escape(self._pkt_filters['observer'])}")
        if self._pkt_filters["path_node"]:
            parts.append(f"path={markup_escape(self._pkt_filters['path_node'])}")
        filt = f"  ({', '.join(parts)})" if parts else ""
        names = ("  path:names", "  path:src+hex", "  path:hex")[2 - self._resolve_path]
        wrap = "  wrap:on" if self._wrap_path else ""
        follow = "" if self._follow else "  follow:off"
        layout = "  layout:bottom" if self._layout_bottom else ""
        count = len(self._all_packets)
        now = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
        err = f"  ERROR: {error}" if error else ""
        self.query_one("#status", Label).update(
            f"{state}{filt}{names}{wrap}{follow}{layout}  {count} packets  last: {now}{err}"
        )

    def action_refresh(self) -> None:
        self.workers.cancel_all()
        self._poll_worker()

    def action_pause(self) -> None:
        self._paused = not self._paused
        if not self._paused:
            self._rebuild_table()
        self._set_status(None)

    def action_filter(self) -> None:
        def apply_filter(value: dict | None) -> None:
            if value is not None:
                self._pkt_filters = value
            self._rebuild_table()
            self._set_status(None)

        self.push_screen(FilterScreen(self._pkt_filters), apply_filter)


class MonitorTab(TabPane):
    """Live MeshCore packet monitor as a TabPane widget for embedding in MeshCoreApp."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("p", "pause", "Pause/Resume"),
        Binding("f", "filter", "Filter"),
        Binding("d", "toggle_detail_panel", "Detail", key_display="(S-)d"),
        Binding("D", "open_detail", "Detail popup", show=False),
        Binding("m", "toggle_map_panel", "Map", key_display="(S-)m"),
        Binding("M", "open_map", "Map popup", show=False),
        Binding("a", "toggle_follow", "Follow"),
        Binding("b", "toggle_layout", "Layout"),
        Binding("n", "toggle_names", "Names"),
        Binding("w", "toggle_wrap", "Wrap"),
        Binding("c", "clear", "Clear"),
    ]
    DEFAULT_CSS = """
    /* === Main layout (right-panel mode, default) === */
    MonitorTab #main_area {
        height: 1fr;
        layout: horizontal;
    }
    MonitorTab DataTable {
        width: 1fr;
        height: 1fr;
    }
    MonitorTab #panel_area {
        display: none;
        layout: vertical;
        width: 60;
        height: 1fr;
        background: $surface;
    }
    MonitorTab #panel_resize {
        display: none;
        width: 1;
        height: 1fr;
        background: $accent 15%;
    }
    MonitorTab #panel_resize:hover {
        background: $accent 50%;
    }
    MonitorTab #detail_side {
        display: none;
        height: 1fr;
        padding: 1 2;
    }
    MonitorTab MapSidePanel {
        display: none;
        height: 1fr;
    }
    /* === Bottom-panel mode === */
    MonitorTab.panels-bottom #main_area {
        layout: vertical;
    }
    MonitorTab.panels-bottom #panel_area {
        layout: horizontal;
        width: 1fr;
        height: 18;
    }
    MonitorTab.panels-bottom #panel_resize {
        width: 1fr;
        height: 1;
    }
    MonitorTab.panels-bottom #detail_side,
    MonitorTab.panels-bottom MapSidePanel {
        width: 1fr;
        height: 1fr;
    }
    /* === Status bar === */
    MonitorTab #status {
        height: 1;
        background: $panel;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        region: str,
        packet_provider: "PacketProvider",
        poll_interval: int = 5,
        channels_path: str | None = None,
    ) -> None:
        super().__init__("F1 Monitor", id="tab_monitor")
        self._region = region
        self.poll_interval = poll_interval
        self._packet_provider = packet_provider
        channels = load_channels(channels_path) if channels_path else []
        self._channel_lookup = build_channel_lookup(channels)
        self._db: dict = {"nodes": {}}
        self._seen_ids: set[str] = set()
        self._paused = False
        self._pkt_filters: dict = {"observer": "", "path_node": ""}
        self._all_packets: list[dict] = []
        self._packets_by_id: dict[str, dict] = {}
        self._displayed: list[dict] = []
        self._resolve_path: int = 2
        self._wrap_path: bool = False
        self._detail_panel_open: bool = False
        self._map_panel_open: bool = False
        self._follow: bool = False
        self._layout_bottom: bool = False

    def compose(self) -> ComposeResult:
        with Container(id="main_area"):
            yield DataTable(id="packets")
            yield ResizeHandle(
                target_getter=lambda: self.query_one("#panel_area"),
                min_size=20,
                max_size=150,
                id="panel_resize",
            )
            with Container(id="panel_area"):
                with VerticalScroll(id="detail_side"):
                    yield Static("", id="detail_content", markup=True)
                yield MapSidePanel(id="map_side")
        yield Label("", id="status")

    def on_mount(self) -> None:
        self._db = load_db()
        table = self.query_one("#packets", DataTable)
        table.add_columns("Time", "Observer", "Type", "SNR", "RSSI", "Src→Relays")
        table.cursor_type = "row"
        self._set_status(None)
        self._poll_worker()

    @work(thread=True, exclusive=True)
    def _poll_worker(self) -> None:
        worker = get_current_worker()
        while not worker.is_cancelled:
            try:
                packets = self._packet_provider.fetch_packets(self._region, limit=500)
                self.app.call_from_thread(self._ingest_packets, packets)
            except Exception as e:
                self.app.call_from_thread(self._set_status, str(e))
            for _ in range(self.poll_interval * 10):
                if worker.is_cancelled:
                    return
                time.sleep(0.1)

    def _ingest_packets(self, packets: list[dict]) -> None:
        region = self._region.upper()
        new = [
            p for p in packets
            if p.get("id") not in self._seen_ids
            and region in [r.upper() for r in (p.get("regions") or [])]
        ]
        if not new:
            self._set_status(None)
            return
        db_dirty = False
        for p in new:
            self._seen_ids.add(p["id"])
            pkt_dec = decode_packet(p.get("raw_data", "") or "")
            p["_path"] = pkt_dec.get("path") or []
            p["_decoded"] = pkt_dec
            decoded_payload = pkt_dec.get("decoded") or {}
            p["_src_hash"] = decoded_payload.get("src_hash", "")
            p["_route_type"] = pkt_dec.get("route_type", "")
            p["_path_hop_size"] = pkt_dec.get("path_hop_size", 1)
            if pkt_dec.get("payload_type") == "Advert" and decoded_payload.get("public_key"):
                pub = decoded_payload["public_key"]
                name = decoded_payload.get("name") or pub[:8]
                role = decoded_payload.get("role", "")
                lat = decoded_payload.get("lat")
                lon = decoded_payload.get("lon")
                if learn_from_advert(self._db, pub, name, role, lat, lon):
                    db_dirty = True
                p["_src_hash"] = pub[:12]
            if (pkt_dec.get("payload_type") in GROUP_TYPES
                    and self._channel_lookup):
                raw_payload = bytes.fromhex(pkt_dec.get("payload_hex", "") or "")
                if len(raw_payload) >= 3:
                    ch_byte = raw_payload[0]
                    mac = raw_payload[1:3]
                    ciphertext = raw_payload[3:]
                    result = try_decrypt(ch_byte, mac, ciphertext, self._channel_lookup)
                    if result:
                        p["_decrypted"] = result
            self._packets_by_id[p["id"]] = p
        if db_dirty:
            save_db(self._db)
        self._all_packets = (new + self._all_packets)[:MAX_PACKETS]
        visible_ids = {p["id"] for p in self._all_packets}
        self._packets_by_id = {k: v for k, v in self._packets_by_id.items() if k in visible_ids}
        if not self._paused:
            self._rebuild_table()
        self._set_status(None)

    def _node_matches(self, term: str, node_id: str) -> bool:
        """True if term matches the node by name substring or hex address prefix."""
        t = term.lower().replace(" ", "")
        return t in resolve_name(node_id, self._db).lower() or node_id.lower().startswith(t)

    def _packet_matches(self, p: dict) -> bool:
        f = self._pkt_filters
        obs_id = p.get("origin_id", "")
        path_ids = p.get("_path") or []
        src_hash = p.get("_src_hash", "")

        if f["observer"]:
            t = f["observer"].lower()
            origin_name = (p.get("origin") or "").lower()
            if t not in origin_name and not self._node_matches(f["observer"], obs_id):
                return False

        if f["path_node"]:
            obs_id_lower = obs_id.lower()
            def _is_obs(nid: str) -> bool:
                n = nid.lower()
                return obs_id_lower.startswith(n) or n.startswith(obs_id_lower)
            path_and_src = [nid for nid in list(path_ids) + ([src_hash] if src_hash else [])
                            if nid and not _is_obs(nid)]
            if not any(self._node_matches(f["path_node"], nid) for nid in path_and_src):
                return False

        return True

    def _rebuild_table(self) -> None:
        table = self.query_one("#packets", DataTable)
        pinned_id: str | None = None
        if not self._follow and self._displayed:
            cr = table.cursor_row
            if cr < len(self._displayed):
                pinned_id = self._displayed[cr].get("id")
        table.clear()
        self._displayed = [p for p in self._all_packets if self._packet_matches(p)]
        for p in self._displayed:
            heard = p.get("heard_at", "")
            try:
                dt = datetime.fromisoformat(heard.replace("Z", "+00:00"))
                time_str = dt.astimezone().strftime("%H:%M:%S")
            except Exception:
                time_str = heard[:8]
            node = p.get("origin") or resolve_name(p.get("origin_id", ""), self._db)
            ptype = format_payload_type(p.get("payload_type", ""))
            snr = f"{p['snr']:.1f}" if p.get("snr") is not None else "-"
            rssi = str(p.get("rssi", "-"))
            raw_path = p.get("_path") or []
            decrypted = p.get("_decrypted") or {}
            src_display = decrypted.get("sender", "") or p.get("_src_hash", "")
            path = format_path(raw_path, self._db, resolve=self._resolve_path,
                               src_hash=src_display,
                               route_type=p.get("_route_type", ""),
                               hop_size=p.get("_path_hop_size", 1),
                               ptype=p.get("payload_type", ""))
            if self._wrap_path:
                wrap_width = max(20, self.app.size.width - 58)
                lines = textwrap.wrap(path, width=wrap_width) or [path]
                path_cell = Text.from_markup("\n".join(lines))
                row_height = len(lines)
            else:
                path_cell = Text.from_markup(path)
                row_height = 1
            table.add_row(time_str, node, ptype, snr, rssi, path_cell, height=row_height, key=p["id"])
        target_row = 0
        if pinned_id:
            for i, p in enumerate(self._displayed):
                if p.get("id") == pinned_id:
                    target_row = i
                    break
        if target_row > 0:
            table.move_cursor(row=target_row)
        if self._displayed:
            if self._detail_panel_open:
                self._update_detail_side(target_row)
            if self._map_panel_open:
                self._update_map_side(target_row)

    def action_open_detail(self) -> None:
        if not self._displayed:
            return
        row = self.query_one("#packets", DataTable).cursor_row
        self.app.push_screen(PacketDetailScreen(self._displayed, row, self._db))

    def action_open_map(self) -> None:
        if not self._displayed:
            return
        row = self.query_one("#packets", DataTable).cursor_row
        self.app.push_screen(PacketMapScreen(self._displayed, row, self._db))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        row = event.cursor_row
        if not self._displayed or row >= len(self._displayed):
            return
        if self._detail_panel_open:
            self._update_detail_side(row)
        if self._map_panel_open:
            self._update_map_side(row)

    def _update_detail_side(self, row: int) -> None:
        if not self._displayed or row >= len(self._displayed):
            return
        p = self._displayed[row]
        self.query_one("#detail_content", Static).update(_build_detail_text(p, self._db))

    def _update_map_side(self, row: int) -> None:
        if not self._displayed or row >= len(self._displayed):
            return
        self.query_one(MapSidePanel).load_packet(self._displayed, row, self._db)

    def _sync_panel_area(self) -> None:
        """Show #panel_area (and its resize handle) iff at least one side panel is open."""
        visible = self._detail_panel_open or self._map_panel_open
        self.query_one("#panel_area").display = visible
        self.query_one("#panel_resize").display = visible

    def action_toggle_detail_panel(self) -> None:
        self._detail_panel_open = not self._detail_panel_open
        self.query_one("#detail_side", VerticalScroll).display = self._detail_panel_open
        self._sync_panel_area()
        if self._detail_panel_open:
            row = self.query_one("#packets", DataTable).cursor_row
            self._update_detail_side(row)

    def action_toggle_map_panel(self) -> None:
        self._map_panel_open = not self._map_panel_open
        self.query_one(MapSidePanel).display = self._map_panel_open
        self._sync_panel_area()
        if self._map_panel_open:
            row = self.query_one("#packets", DataTable).cursor_row
            self._update_map_side(row)

    def action_toggle_follow(self) -> None:
        self._follow = not self._follow
        self._set_status(None)

    def action_toggle_layout(self) -> None:
        self._layout_bottom = not self._layout_bottom
        if self._layout_bottom:
            self.add_class("panels-bottom")
        else:
            self.remove_class("panels-bottom")
        self._set_status(None)

    def action_toggle_names(self) -> None:
        self._resolve_path = (self._resolve_path - 1) % 3
        self._rebuild_table()
        self._set_status(None)

    def action_toggle_wrap(self) -> None:
        self._wrap_path = not self._wrap_path
        self._rebuild_table()
        self._set_status(None)

    def action_clear(self) -> None:
        self._all_packets = []
        self._displayed = []
        self._seen_ids = set()
        self._packets_by_id = {}
        self.query_one("#packets", DataTable).clear()
        self.query_one("#detail_content", Static).update("")
        self.query_one(MapSidePanel).clear()
        self._set_status(None)

    def _set_status(self, error: str | None) -> None:
        state = "[PAUSED]" if self._paused else "[LIVE]"
        parts = []
        if self._pkt_filters["observer"]:
            parts.append(f"obs={markup_escape(self._pkt_filters['observer'])}")
        if self._pkt_filters["path_node"]:
            parts.append(f"path={markup_escape(self._pkt_filters['path_node'])}")
        filt = f"  ({', '.join(parts)})" if parts else ""
        names = ("  path:names", "  path:src+hex", "  path:hex")[2 - self._resolve_path]
        wrap = "  wrap:on" if self._wrap_path else ""
        follow = "" if self._follow else "  follow:off"
        layout = "  layout:bottom" if self._layout_bottom else ""
        count = len(self._all_packets)
        now = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
        err = f"  ERROR: {error}" if error else ""
        self.query_one("#status", Label).update(
            f"{state}{filt}{names}{wrap}{follow}{layout}  {count} packets  last: {now}{err}"
        )

    def action_refresh(self) -> None:
        self.workers.cancel_all()
        self._poll_worker()

    def action_pause(self) -> None:
        self._paused = not self._paused
        if not self._paused:
            self._rebuild_table()
        self._set_status(None)

    def action_filter(self) -> None:
        def apply_filter(value: dict | None) -> None:
            if value is not None:
                self._pkt_filters = value
            self._rebuild_table()
            self._set_status(None)

        self.app.push_screen(FilterScreen(self._pkt_filters), apply_filter)


def run_monitor(
    region: str,
    packet_provider: "PacketProvider",
    poll_interval: int = 5,
    channels_path: str | None = None,
) -> None:
    """Launch MeshCoreApp with the Monitor tab active (companion tabs optional)."""
    from meshcore_tools.app import MeshCoreApp
    MeshCoreApp(
        region=region,
        packet_provider=packet_provider,
        poll_interval=poll_interval,
        channels_path=channels_path,
    ).run()
