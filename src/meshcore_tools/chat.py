"""ChatTab — companion channel messaging widget."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.markup import escape as markup_escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.widgets import Input, Label, ListItem, ListView, Static, TabPane

if TYPE_CHECKING:
    from meshcore_tools.companion import CompanionManager

_MAX_MSG_LEN = 133


class ChatTab(TabPane):
    """Chat tab: channel list on the left + message log + input bar on the right."""

    BINDINGS = [
        Binding("enter", "send_message", "Send", show=False),
        Binding("left", "prev_channel", "Prev channel", show=False),
        Binding("right", "next_channel", "Next channel", show=False),
    ]

    DEFAULT_CSS = """
    ChatTab {
        height: 1fr;
        layout: horizontal;
    }
    ChatTab #channel_list {
        width: 20;
        height: 1fr;
        border-right: solid $accent;
    }
    ChatTab #right_pane {
        width: 1fr;
        height: 1fr;
        layout: vertical;
    }
    ChatTab #msg_log {
        height: 1fr;
        padding: 1 2;
    }
    ChatTab #input_bar {
        height: 3;
        layout: horizontal;
        padding: 0 1;
        background: $panel;
    }
    ChatTab #msg_input {
        width: 1fr;
    }
    ChatTab #char_count {
        width: 8;
        content-align: right middle;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__("F2 Channels", id="tab_chat")
        self._channels: list[dict] = []
        self._active_channel_idx: int = 0
        self._messages: dict[int, list[dict]] = {}

    def compose(self) -> ComposeResult:
        yield ListView(id="channel_list")
        with Container(id="right_pane"):
            with VerticalScroll(id="msg_log"):
                yield Static("", id="msg_content", markup=True)
            with Container(id="input_bar"):
                yield Input(
                    placeholder="type a message…",
                    id="msg_input",
                    max_length=_MAX_MSG_LEN,
                )
                yield Label(f"0/{_MAX_MSG_LEN}", id="char_count")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "msg_input":
            count = len(event.value)
            self.query_one("#char_count", Label).update(f"{count}/{_MAX_MSG_LEN}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "msg_input":
            self._do_send(event.value)

    def _do_send(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.query_one("#msg_input", Input).value = ""
        self.query_one("#char_count", Label).update(f"0/{_MAX_MSG_LEN}")
        msg_entry = {
            "sender": "you",
            "text": text,
            "ts": int(datetime.now(timezone.utc).timestamp()),
            "status": "⏳",
        }
        self._messages.setdefault(self._active_channel_idx, []).append(msg_entry)
        self._refresh_log()
        self._send_worker(self._active_channel_idx, text, msg_entry)

    @work(thread=False, exclusive=False)
    async def _send_worker(
        self, channel_idx: int, text: str, msg_entry: dict
    ) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if manager is None:
            msg_entry["status"] = "✗"
            self._refresh_log()
            return
        success = await manager.send_channel_message(channel_idx, text)
        msg_entry["status"] = "✓" if success else "✗"
        self._refresh_log()

    def _refresh_log(self) -> None:
        msgs = self._messages.get(self._active_channel_idx, [])
        lines: list[str] = []
        for m in msgs:
            try:
                ts = datetime.fromtimestamp(m["ts"], tz=timezone.utc).astimezone().strftime("%H:%M")
            except (ValueError, OSError, TypeError):
                ts = "??:??"
            sender = markup_escape(m["sender"])
            text = markup_escape(m["text"])
            status = m.get("status", "")
            if m["sender"] == "you":
                lines.append(f"[dim]{ts}[/dim]  [bold]you:[/bold]  {text}  {status}")
            else:
                lines.append(f"[dim]{ts}[/dim]  {sender}:  {text}")
        self.query_one("#msg_content", Static).update("\n".join(lines))
        self.query_one("#msg_log", VerticalScroll).scroll_end(animate=False)

    def populate_channels(self, channels: list[dict]) -> None:
        """Called by MeshCoreApp after channels are fetched from the device."""
        self._channels = channels
        list_view = self.query_one("#channel_list", ListView)
        list_view.clear()
        for ch in self._channels:
            list_view.append(ListItem(Label(ch["name"])))
        if channels:
            self._active_channel_idx = channels[0]["idx"]
            list_view.index = 0
            self._refresh_log()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "channel_list":
            return
        idx = event.list_view.index
        if idx is not None and idx < len(self._channels):
            self._active_channel_idx = self._channels[idx]["idx"]
            self._refresh_log()

    def _select_channel(self, channel_idx: int) -> None:
        self._active_channel_idx = channel_idx
        idxs = [ch["idx"] for ch in self._channels]
        if channel_idx in idxs:
            list_view = self.query_one("#channel_list", ListView)
            list_view.index = idxs.index(channel_idx)
        self._refresh_log()

    def action_prev_channel(self) -> None:
        if not self._channels:
            return
        idxs = [ch["idx"] for ch in self._channels]
        pos = idxs.index(self._active_channel_idx) if self._active_channel_idx in idxs else 0
        self._select_channel(idxs[(pos - 1) % len(idxs)])

    def action_next_channel(self) -> None:
        if not self._channels:
            return
        idxs = [ch["idx"] for ch in self._channels]
        pos = idxs.index(self._active_channel_idx) if self._active_channel_idx in idxs else 0
        self._select_channel(idxs[(pos + 1) % len(idxs)])

    def receive_channel_message(
        self,
        channel_idx: int,
        channel_name: str,
        sender: str,
        text: str,
        timestamp: int,
    ) -> None:
        """Called by MeshCoreApp when a ChannelMessage is received."""
        self._messages.setdefault(channel_idx, []).append({
            "sender": sender,
            "text": text,
            "ts": timestamp,
            "status": "",
        })
        if channel_idx == self._active_channel_idx:
            self._refresh_log()

    def clear(self) -> None:
        """Clear all messages and channels (called on disconnect)."""
        self._messages.clear()
        self._active_channel_idx = 0
        self._refresh_log()
        self.populate_channels([])
