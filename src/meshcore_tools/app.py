"""MeshCoreApp — unified TUI entry point with Monitor, Chat, and Repeater tabs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape as markup_escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, TabbedContent

if TYPE_CHECKING:
    from meshcore_tools.providers import PacketProvider

from meshcore_tools.logtab import LogPanel, LogTab, LogView, TuiLogHandler
from meshcore_tools.monitor import MonitorTab
from meshcore_tools.connection import (
    ConnectScreen,
    ConnectionConfig,
    load_connection_config,
    save_connection_config,
)

try:
    from meshcore_tools.companion import (
        CompanionManager,
        ChannelMessage,
        CompanionConnected,
        CompanionConnectionError,
        CompanionDisconnected,
        ContactsUpdated,
        _MESHCORE_AVAILABLE as _meshcore_pkg_available,
    )
    from meshcore_tools.chat import ChatTab
    from meshcore_tools.repeaters import RepeatersTab
    COMPANION_AVAILABLE = _meshcore_pkg_available
except ImportError:
    COMPANION_AVAILABLE = False


class MeshCoreApp(App):
    """Unified MeshCore TUI: Monitor + optional Chat and Repeater tabs."""

    TITLE = "MeshCore Tools"

    BINDINGS = [
        Binding("f1", "switch_tab('tab_monitor')", "Monitor"),
        Binding("f2", "switch_tab('tab_chat')", "Chat", show=False),
        Binding("f3", "switch_tab('tab_repeaters')", "Repeaters", show=False),
        Binding("f4", "switch_tab('tab_logs')", "Logs", show=False),
        Binding("l", "toggle_log_panel", "Log Panel"),
        Binding("+", "log_panel_grow", "Log +", show=False),
        Binding("-", "log_panel_shrink", "Log -", show=False),
        Binding("C", "connect", "Connect"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    MeshCoreApp TabbedContent {
        height: 1fr;
    }
    MeshCoreApp TabbedContent ContentSwitcher {
        height: 1fr;
    }
    """

    def __init__(
        self,
        region: str,
        packet_provider: "PacketProvider",
        poll_interval: int = 5,
        channels_path: str | None = None,
    ) -> None:
        super().__init__()
        self._region = region
        self._packet_provider = packet_provider
        self._poll_interval = poll_interval
        self._channels_path = channels_path
        self.companion: CompanionManager | None = None
        self._log_panel_open: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent():
            yield MonitorTab(
                region=self._region,
                packet_provider=self._packet_provider,
                poll_interval=self._poll_interval,
                channels_path=self._channels_path,
            )
            if COMPANION_AVAILABLE:
                yield ChatTab()
                yield RepeatersTab()
            yield LogTab()
        yield LogPanel(id="log_panel")
        yield Footer()

    def on_mount(self) -> None:
        import logging
        tab_view = self.query_one(LogTab).query_one(LogView)
        panel_view = self.query_one(LogPanel).query_one(LogView)
        logging.getLogger().addHandler(TuiLogHandler(tab_view, panel_view))
        logging.getLogger().setLevel(logging.DEBUG)

        self.sub_title = f"region={self._region}  poll={self._poll_interval}s"
        if not COMPANION_AVAILABLE:
            self.sub_title += "  [companion features require: pip install meshcore-tools[companion]]"
            return
        self.companion = CompanionManager(self)
        config = load_connection_config()
        if config is not None:
            if config.type == "ble":
                # BLE auto-connect requires a fresh device scan (Bleak on Linux
                # runs an internal scan when connecting by MAC alone, which
                # blocks any concurrent manual scan). Prompt user to scan instead.
                self.sub_title += "  BLE — press C to scan and connect"
            else:
                self._do_connect(config)

    def action_switch_tab(self, tab_id: str) -> None:
        if tab_id in ("tab_chat", "tab_repeaters") and not COMPANION_AVAILABLE:
            return
        try:
            self.query_one(TabbedContent).active = tab_id
        except Exception:
            pass

    def _sync_log_panel(self) -> None:
        logs_tab_active = self.query_one(TabbedContent).active == "tab_logs"
        self.query_one(LogPanel).display = self._log_panel_open and not logs_tab_active

    def action_toggle_log_panel(self) -> None:
        self._log_panel_open = not self._log_panel_open
        self._sync_log_panel()

    def action_log_panel_grow(self) -> None:
        panel = self.query_one(LogPanel)
        if panel.display:
            h = panel.styles.height
            panel.styles.height = min((h.value if h else 10) + 2, 40)

    def action_log_panel_shrink(self) -> None:
        panel = self.query_one(LogPanel)
        if panel.display:
            h = panel.styles.height
            panel.styles.height = max((h.value if h else 10) - 2, 4)

    def on_tabbed_content_tab_activated(self, _: TabbedContent.TabActivated) -> None:
        self._sync_log_panel()

    def action_connect(self) -> None:
        if not COMPANION_AVAILABLE:
            return
        current_config = load_connection_config()
        self.push_screen(
            ConnectScreen(current=current_config),
            self._on_connect_screen_result,
        )

    def _on_connect_screen_result(self, config: ConnectionConfig | None) -> None:
        if config is None:
            return
        save_connection_config(config)
        self._do_connect(config)

    def _do_connect(self, config: ConnectionConfig) -> None:
        self._connect_worker(config)

    @work(thread=False, exclusive=True)
    async def _connect_worker(self, config: ConnectionConfig) -> None:
        if self.companion is None:
            return
        await self.companion.disconnect()
        self.sub_title = f"region={self._region}  connecting…"
        await self.companion.connect(config)

    def on_companion_connected(self, message: "CompanionConnected") -> None:
        name = markup_escape(message.node_name)
        self.sub_title = f"region={self._region}  companion: {name} [connected]"

    def on_companion_disconnected(self, _: "CompanionDisconnected") -> None:
        self.sub_title = f"region={self._region}  companion: [disconnected]"
        if COMPANION_AVAILABLE:
            try:
                self.query_one(ChatTab).clear()
                self.query_one(RepeatersTab).clear()
            except Exception:
                pass

    def on_companion_connection_error(self, message: "CompanionConnectionError") -> None:
        self.sub_title = f"region={self._region}  companion error: {message.reason}"

    def on_contacts_updated(self, message: "ContactsUpdated") -> None:
        if not COMPANION_AVAILABLE:
            return
        try:
            self.query_one(ChatTab).populate_channels(message.contacts)
            self.query_one(RepeatersTab).populate_repeaters(message.contacts)
        except Exception:
            pass

    def on_channel_message(self, message: "ChannelMessage") -> None:
        if not COMPANION_AVAILABLE:
            return
        try:
            self.query_one(ChatTab).receive_channel_message(
                channel_idx=message.channel_idx,
                channel_name=message.channel_name,
                sender=message.sender,
                text=message.text,
                timestamp=message.timestamp,
            )
        except Exception:
            pass
