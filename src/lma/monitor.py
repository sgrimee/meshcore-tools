"""Live packet monitoring TUI using Textual."""

from __future__ import annotations

import textwrap
import time
from datetime import datetime, timezone

from rich.markup import escape as markup_escape

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static
from textual.worker import get_current_worker

from lma.api import DEFAULT_REGION, fetch_packets
from lma.db import load_db
from lma.decoder import decode_packet

MAX_PACKETS = 500


def resolve_name(origin_id: str, db: dict) -> str:
    """Resolve a key prefix to a display name.

    Returns the node name if unambiguous, 'name1/name2?' if multiple matches,
    or the raw 8-char prefix if no match found.
    """
    origin_id = origin_id.lower()
    names = [
        db["nodes"][key]["name"]
        for key in db.get("nodes", {})
        if key.startswith(origin_id) or origin_id.startswith(key[: len(origin_id)])
    ]
    if not names:
        return origin_id[:8]
    if len(names) == 1:
        return names[0]
    return "/".join(names) + "?"


def decode_path_from_raw(raw_data: str) -> list[str] | None:
    """Decode path hops directly from raw MeshCore packet bytes.

    Wire format (non-transport):
      Byte 0:  header  (bits 0-1 = route_type)
      Byte 1:  path_len  (bits 7-6 = hash_size-1, bits 5-0 = hop count)
      Bytes 2+: hop data  (count × hash_size bytes)

    Transport packets (route_type 0x00 or 0x03) have 4 extra bytes
    (transport codes) before path_len, so path_len is at byte 5.

    Returns list of hex strings (one per hop) or None on any parse error.
    """
    try:
        raw = bytes.fromhex(raw_data)
        if len(raw) < 2:
            return None
        route_type = raw[0] & 0x03
        path_len_offset = 5 if route_type in (0x00, 0x03) else 1
        if len(raw) <= path_len_offset:
            return None
        path_len_byte = raw[path_len_offset]
        hash_size = (path_len_byte >> 6) + 1
        count = path_len_byte & 0x3F
        path_start = path_len_offset + 1
        if len(raw) < path_start + count * hash_size:
            return None
        return [
            raw[path_start + i * hash_size: path_start + (i + 1) * hash_size].hex()
            for i in range(count)
        ]
    except Exception:
        return None


def get_source(path_list: list, db: dict, resolve: bool = True) -> str:
    """Return the source node (first path element)."""
    if not path_list:
        return "?"
    return resolve_name(path_list[0], db) if resolve else path_list[0]


def format_path(path_list: list, db: dict, resolve: bool = True) -> str:
    """Format full path: source → relay1 → relay2 → ..."""
    if not path_list:
        return "direct"
    if not resolve:
        return " → ".join(hop[:8] for hop in path_list)
    return " → ".join(resolve_name(hop, db) for hop in path_list)


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


def _fmt_hash(h: str, db: dict) -> str:
    """Format a short hash with its resolved name."""
    name = resolve_name(h, db)
    return f"[dim]{h}[/dim]  {name}"


def _build_detail_text(packet: dict, db: dict) -> str:
    p = packet
    dec = decode_packet(p.get("raw_data", "") or "")

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

    # --- Path decoded from raw ---
    lines.append("")
    full_path = dec.get("path") or p.get("_path") or []
    hop_size = dec.get("path_hop_size", 1)
    if hop_size > 1:
        lines.append(f"[dim]Path:[/dim]       ({hop_size}-byte node addresses)")
    if not full_path:
        lines.append("[dim]Source:[/dim]     unknown (direct)")
        lines.append("[dim]Relays:[/dim]     none")
    else:
        src = full_path[0]
        lines.append(f"[dim]Source:[/dim]     {_fmt_hash(src, db)}")
        relays = full_path[1:]
        if not relays:
            lines.append("[dim]Relays:[/dim]     none")
        else:
            lines.append("[dim]Relays:[/dim]")
            for hop in relays:
                lines.append(f"  {_fmt_hash(hop, db)}")

    # --- Decoded payload ---
    lines.append("")
    payload_dec = dec.get("decoded", {})
    if dec.get("error"):
        lines.append(f"[dim]Decode error:[/dim] {dec['error']}")
    elif payload_dec:
        lines += _fmt_payload(ptype, payload_dec, db)
    elif dec.get("payload_hex"):
        lines.append(f"[dim]Payload:[/dim]    {dec['payload_hex'][:64]}"
                     + ("…" if len(dec.get("payload_hex", "")) > 64 else ""))

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


def _fmt_payload(ptype: str, d: dict, db: dict) -> list[str]:
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
        src = d.get("src_hash", "")
        dst = d.get("dest_hash", "")
        lines.append(f"[dim]Src:[/dim]        {_fmt_hash(src, db)}")
        lines.append(f"[dim]Dst:[/dim]        {_fmt_hash(dst, db)}")
        lines.append(f"[dim]MAC:[/dim]        {d.get('cipher_mac', '-')}")
        lines.append(f"[dim]Content:[/dim]    encrypted ({d.get('ciphertext_len', 0)} bytes)")

    elif ptype in ("GroupText", "GroupData"):
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
        yield Static("Any node (observer, source or relay):", markup=False)
        yield Input(value=self._pkt_filters.get("node", ""), placeholder="e.g.  relay  or  ab cd", id="node")
        yield Static("Relay node (in path):", markup=False)
        yield Input(value=self._pkt_filters.get("path_node", ""), placeholder="e.g.  relay  or  ab cd", id="path_node")
        yield Static("↵ apply · Esc clear all · Tab next field", id="hint", markup=False)

    def on_mount(self) -> None:
        self.query_one("#observer", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._apply()

    def _apply(self) -> None:
        self.dismiss({
            "observer": self.query_one("#observer", Input).value.strip(),
            "node": self.query_one("#node", Input).value.strip(),
            "path_node": self.query_one("#path_node", Input).value.strip(),
        })

    def action_clear_all(self) -> None:
        self.dismiss({"observer": "", "node": "", "path_node": ""})


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
        header = f"[dim]({self._index + 1}/{n}  ↑↓ navigate)[/dim]\n"
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


class PacketMonitorApp(App):
    """Live MeshCore packet monitor."""

    TITLE = "MeshCore Monitor"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("p", "pause", "Pause/Resume"),
        Binding("f", "filter", "Filter"),
        Binding("n", "toggle_names", "Names"),
        Binding("w", "toggle_wrap", "Wrap"),
        Binding("c", "clear", "Clear"),
    ]
    CSS = """
    DataTable {
        height: 1fr;
    }
    #status {
        height: 1;
        background: $panel;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, region: str = DEFAULT_REGION, poll_interval: int = 5):
        super().__init__()
        self.region = region
        self.poll_interval = poll_interval
        self._db: dict = {"nodes": {}}
        self._seen_ids: set[str] = set()
        self._paused = False
        self._pkt_filters: dict = {"observer": "", "node": "", "path_node": ""}
        self._all_packets: list[dict] = []
        self._packets_by_id: dict[str, dict] = {}
        self._displayed: list[dict] = []
        self._resolve_path: bool = True
        self._wrap_path: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(id="packets")
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
                packets = fetch_packets(self.region, limit=500)
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
        for p in new:
            self._seen_ids.add(p["id"])
            decoded = decode_path_from_raw(p.get("raw_data", ""))
            p["_path"] = decoded if decoded is not None else (p.get("path") or [])
            self._packets_by_id[p["id"]] = p
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

        if f["observer"]:
            t = f["observer"].lower()
            origin_name = (p.get("origin") or "").lower()
            if t not in origin_name and not self._node_matches(f["observer"], obs_id):
                return False

        if f["node"]:
            all_ids = [obs_id] + list(path_ids)
            if not any(self._node_matches(f["node"], nid) for nid in all_ids):
                return False

        if f["path_node"] and not any(self._node_matches(f["path_node"], nid) for nid in path_ids):
            return False

        return True

    def _rebuild_table(self) -> None:
        table = self.query_one("#packets", DataTable)
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
            path = format_path(raw_path, self._db, resolve=self._resolve_path)
            if self._wrap_path:
                wrap_width = max(20, self.size.width - 58)
                lines = textwrap.wrap(path, width=wrap_width) or [path]
                path_cell = "\n".join(lines)
                row_height = len(lines)
            else:
                path_cell = path
                row_height = 1
            table.add_row(time_str, node, ptype, snr, rssi, path_cell, height=row_height, key=p["id"])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if not self._displayed:
            return
        self.push_screen(PacketDetailScreen(self._displayed, event.cursor_row, self._db))

    def action_toggle_names(self) -> None:
        self._resolve_path = not self._resolve_path
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
        self._set_status(None)

    def _set_status(self, error: str | None) -> None:
        state = "[PAUSED]" if self._paused else "[LIVE]"
        parts = []
        if self._pkt_filters["observer"]: parts.append(f"obs={markup_escape(self._pkt_filters['observer'])}")
        if self._pkt_filters["node"]: parts.append(f"node={markup_escape(self._pkt_filters['node'])}")
        if self._pkt_filters["path_node"]: parts.append(f"path={markup_escape(self._pkt_filters['path_node'])}")
        filt = f"  ({', '.join(parts)})" if parts else ""
        names = "  path:names" if self._resolve_path else "  path:hops"
        wrap = "  wrap:on" if self._wrap_path else ""
        count = len(self._all_packets)
        now = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
        err = f"  ERROR: {error}" if error else ""
        self.query_one("#status", Label).update(
            f"{state}{filt}{names}{wrap}  {count} packets  last: {now}{err}"
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


def run_monitor(region: str = DEFAULT_REGION, poll_interval: int = 5) -> None:
    PacketMonitorApp(region=region, poll_interval=poll_interval).run()
