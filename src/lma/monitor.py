"""Live packet monitoring TUI using Textual."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static
from textual.worker import get_current_worker

from lma.api import DEFAULT_REGION, fetch_packets
from lma.db import load_db

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


def format_path(path_list: list, db: dict, resolve: bool = True) -> str:
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


def _build_detail_text(packet: dict, db: dict) -> str:
    p = packet
    node_name = resolve_name(p.get("origin_id", ""), db)
    lines = [
        "[bold]Packet detail[/bold]",
        "",
        f"[dim]Node:[/dim]       {node_name}",
        f"[dim]Origin ID:[/dim]  {p.get('origin_id', '-')}",
        f"[dim]Heard at:[/dim]   {fmt_ts(p.get('heard_at', ''))}",
        f"[dim]Type:[/dim]       {p.get('payload_type', '-')}",
        f"[dim]Route:[/dim]      {p.get('route_type', '-')}",
        f"[dim]SNR:[/dim]        {p.get('snr', '-')}",
        f"[dim]RSSI:[/dim]       {p.get('rssi', '-')}",
        f"[dim]Score:[/dim]      {p.get('score', '-')}",
        "",
    ]

    path = p.get("path") or []
    if not path:
        lines.append("[dim]Path:[/dim]       direct")
    else:
        lines.append("[dim]Path:[/dim]")
        for hop in path:
            name = resolve_name(hop, db)
            lines.append(f"  [dim]{fmt_key_prefix(hop)}[/dim]  {name}")

    decoded = p.get("decoded_payload")
    if decoded:
        lines.append("")
        lines.append("[dim]Decoded payload:[/dim]")
        if isinstance(decoded, dict):
            for k, v in decoded.items():
                lines.append(f"  {k}: {v}")
        else:
            lines.append(f"  {decoded}")

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


class FilterScreen(ModalScreen[str]):
    """Modal dialog for filtering by node name."""

    DEFAULT_CSS = """
    FilterScreen {
        align: center middle;
    }
    FilterScreen > Label {
        width: 44;
        padding: 1 2 0 2;
        background: $surface;
    }
    FilterScreen > Input {
        width: 44;
        border: solid $accent;
        background: $surface;
        padding: 0 1;
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Filter by node name (empty = show all):")
        yield Input(placeholder="node name...")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss("")


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
        self._filter = ""
        self._all_packets: list[dict] = []
        self._packets_by_id: dict[str, dict] = {}
        self._displayed: list[dict] = []
        self._resolve_path: bool = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(id="packets")
        yield Label("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._db = load_db()
        table = self.query_one("#packets", DataTable)
        table.add_columns("Time", "Node", "Type", "SNR", "RSSI", "Path")
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
            self._packets_by_id[p["id"]] = p
        self._all_packets = (new + self._all_packets)[:MAX_PACKETS]
        visible_ids = {p["id"] for p in self._all_packets}
        self._packets_by_id = {k: v for k, v in self._packets_by_id.items() if k in visible_ids}
        if not self._paused:
            self._rebuild_table()
        self._set_status(None)

    def _rebuild_table(self) -> None:
        table = self.query_one("#packets", DataTable)
        table.clear()
        self._displayed = [
            p for p in self._all_packets
            if not self._filter
            or self._filter.lower() in resolve_name(p.get("origin_id", ""), self._db).lower()
        ]
        for p in self._displayed:
            heard = p.get("heard_at", "")
            try:
                dt = datetime.fromisoformat(heard.replace("Z", "+00:00"))
                time_str = dt.astimezone().strftime("%H:%M:%S")
            except Exception:
                time_str = heard[:8]
            node = resolve_name(p.get("origin_id", ""), self._db)
            ptype = format_payload_type(p.get("payload_type", ""))
            snr = f"{p['snr']:.1f}" if p.get("snr") is not None else "-"
            rssi = str(p.get("rssi", "-"))
            path = format_path(p.get("path") or [], self._db, resolve=self._resolve_path)
            table.add_row(time_str, node, ptype, snr, rssi, path, key=p["id"])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if not self._displayed:
            return
        self.push_screen(PacketDetailScreen(self._displayed, event.cursor_row, self._db))

    def action_toggle_names(self) -> None:
        self._resolve_path = not self._resolve_path
        self._rebuild_table()
        self._set_status(None)

    def _set_status(self, error: str | None) -> None:
        state = "[PAUSED]" if self._paused else "[LIVE]"
        filt = f"  filter: {self._filter}" if self._filter else ""
        names = "  path:names" if self._resolve_path else "  path:hops"
        count = len(self._all_packets)
        now = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
        err = f"  ERROR: {error}" if error else ""
        self.query_one("#status", Label).update(
            f"{state}{filt}{names}  {count} packets  last: {now}{err}"
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
        def apply_filter(value: str) -> None:
            self._filter = value or ""
            self._rebuild_table()
            self._set_status(None)

        self.push_screen(FilterScreen(), apply_filter)


def run_monitor(region: str = DEFAULT_REGION, poll_interval: int = 5) -> None:
    PacketMonitorApp(region=region, poll_interval=poll_interval).run()
