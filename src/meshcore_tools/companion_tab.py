"""CompanionInfoTab — displays info about the connected companion device and sends commands."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.markup import escape as markup_escape
from textual import work
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Button, Input, Static, TabPane

from meshcore_tools.repeaters import _format_response

if TYPE_CHECKING:
    from meshcore_tools.companion import CompanionManager

# Preferred display order + human-readable labels for known self_info fields
_INFO_LABELS: list[tuple[str, str]] = [
    ("name", "Name"),
    ("public_key", "Public Key"),
    ("firmware_version", "Firmware"),
    ("fw_version", "Firmware"),
    ("battery", "Battery"),
    ("uptime", "Uptime"),
    ("freq", "Frequency"),
    ("bw", "Bandwidth"),
    ("sf", "Spreading Factor"),
    ("tx_power", "TX Power"),
    ("cr", "Coding Rate"),
    ("air_time", "Air Time"),
]
_KNOWN_KEYS = {k for k, _ in _INFO_LABELS}


class CompanionInfoTab(TabPane):
    """F4 tab showing companion device info and a free-form command panel."""

    DEFAULT_CSS = """
    CompanionInfoTab {
        height: 1fr;
        layout: vertical;
    }
    CompanionInfoTab #info_panel {
        height: auto;
        padding: 1 2;
        background: $panel;
        border-bottom: solid $accent;
    }
    CompanionInfoTab #info_header {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    CompanionInfoTab #refresh_btn {
        margin-top: 1;
        width: 12;
    }
    CompanionInfoTab #output_log {
        height: 1fr;
        padding: 1 2;
    }
    CompanionInfoTab #cmd_bar {
        height: 3;
        padding: 0 1;
        background: $panel;
    }
    """

    def __init__(self) -> None:
        super().__init__("F4 Companion", id="tab_companion")
        self._self_info: dict = {}
        self._log_lines: list[str] = []

    def compose(self) -> ComposeResult:
        with Container(id="info_panel"):
            yield Static("[bold]Companion Device[/bold]", id="info_header", markup=True)
            yield Static("[dim]Not connected[/dim]", id="info_content", markup=True)
            yield Button("Refresh", id="refresh_btn")
        with VerticalScroll(id="output_log"):
            yield Static("", id="output_content", markup=True)
        yield Input(placeholder="command", id="cmd_bar")

    def update_info(self, self_info: dict) -> None:
        """Update displayed info from a self_info dict (called by MeshCoreApp on connect)."""
        self._self_info = dict(self_info)
        self._render_info()

    def _render_info(self) -> None:
        info = self._self_info
        if not info:
            self.query_one("#info_content", Static).update("[dim]Not connected[/dim]")
            return

        # Determine column width from labels that have data
        present_labels = [label for key, label in _INFO_LABELS if key in info]
        # Also collect unknown keys
        extra_labels = [
            k.replace("_", " ").title() for k in info if k not in _KNOWN_KEYS
        ]
        all_labels = present_labels + extra_labels
        width = max((len(lbl) for lbl in all_labels), default=10)

        lines: list[str] = []
        seen_keys: set[str] = set()

        for key, label in _INFO_LABELS:
            if key in seen_keys:
                continue
            val = info.get(key)
            if val is None:
                continue
            seen_keys.add(key)
            val_str = str(val)
            # Truncate long hex keys for readability
            if key == "public_key" and len(val_str) > 32:
                val_str = val_str[:32] + "…"
            lbl = label.ljust(width)
            lines.append(
                f"  [dim]{markup_escape(lbl)} :[/dim] {markup_escape(val_str)}"
            )

        # Show any additional fields not in the known list
        for key, val in info.items():
            if key in seen_keys or val is None:
                continue
            label = key.replace("_", " ").title().ljust(width)
            lines.append(
                f"  [dim]{markup_escape(label)} :[/dim] {markup_escape(str(val))}"
            )

        content = "\n".join(lines) if lines else "[dim]No info available[/dim]"
        self.query_one("#info_content", Static).update(content)

    def _log(self, line: str, style: str = "") -> None:
        ts = datetime.now(timezone.utc).astimezone().strftime("%H:%M")
        entry = f"[dim]{ts}[/dim]  {f'[{style}]{line}[/{style}]' if style else line}"
        self._log_lines.append(entry)
        self.query_one("#output_content", Static).update("\n".join(self._log_lines))
        try:
            self.query_one("#output_log", VerticalScroll).scroll_end(animate=False)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh_btn":
            self._do_refresh()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "cmd_bar":
            return
        cmd = event.value.strip().lstrip("/")
        event.input.value = ""
        if not cmd:
            return
        self._do_cmd(cmd)

    @work(thread=False, exclusive=False)
    async def _do_refresh(self) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager or not manager.is_connected:
            self._log("Not connected", "red")
            return
        self._log("Refreshing…", "dim")
        info = manager.get_self_info()
        if info:
            self._self_info = info
            self._render_info()
            self._log("Info refreshed", "green")
        else:
            self._log("No info returned", "yellow")

    @work(thread=False, exclusive=False)
    async def _do_cmd(self, cmd: str) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager or not manager.is_connected:
            self._log("Not connected", "red")
            return
        self._log(f"→ {markup_escape(cmd)}", "cyan")
        result = await manager.send_self_cmd(cmd)
        if result in ("not connected",) or result.startswith("error") or result.startswith("unknown command"):
            self._log(markup_escape(result), "red")
        else:
            self._log(f"[bold]{markup_escape(cmd)}:[/bold]\n{_format_response(result)}", "green")

    def clear(self) -> None:
        """Clear info and log a disconnect event (called by MeshCoreApp on disconnect)."""
        self._self_info = {}
        self._render_info()
        self._log("Disconnected", "dim")
