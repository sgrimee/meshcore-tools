"""ChatTab — companion channel messaging widget."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.markup import escape as markup_escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.widgets import Button, Input, Label, Static, TabPane

if TYPE_CHECKING:
    from meshcore_tools.companion import CompanionManager

_MAX_MSG_LEN = 133


class _ChannelButton(Button):
    """A tab-strip button representing one channel."""

    def __init__(self, label: str, channel_idx: int) -> None:
        super().__init__(label, id=f"chan_{channel_idx}")
        self.channel_idx = channel_idx


class ChatTab(TabPane):
    """Chat tab: channel strip + message log + input bar."""

    BINDINGS = [
        Binding("enter", "send_message", "Send", show=False),
    ]

    DEFAULT_CSS = """
    ChatTab {
        height: 1fr;
        layout: vertical;
    }
    ChatTab #channel_strip {
        height: 3;
        layout: horizontal;
        background: $panel;
        padding: 0 1;
    }
    ChatTab #channel_strip Button {
        margin-right: 1;
        min-width: 12;
    }
    ChatTab #channel_strip Button.-active-channel {
        border: solid $accent;
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
        super().__init__("Chat", id="tab_chat")
        self._channels: list[dict] = []
        self._active_channel_idx: int = 0
        self._messages: dict[int, list[dict]] = {}

    def compose(self) -> ComposeResult:
        with Container(id="channel_strip"):
            yield Static("No channels", id="no_channels_hint")
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

    def populate_channels(self, contacts: list[dict]) -> None:
        """Called by MeshCoreApp after companion connects with fresh contacts.

        TODO: Populate additional channels from contacts list (e.g. per-contact
        private channels). Currently only the #public broadcast channel (idx=0)
        is shown.
        """
        self._channels = [{"idx": 0, "name": "#public"}]
        strip = self.query_one("#channel_strip", Container)
        strip.remove_children()
        for ch in self._channels:
            btn = _ChannelButton(ch["name"], ch["idx"])
            if ch["idx"] == self._active_channel_idx:
                btn.add_class("-active-channel")
            strip.mount(btn)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not isinstance(event.button, _ChannelButton):
            return
        self._active_channel_idx = event.button.channel_idx
        for btn in self.query(_ChannelButton):
            btn.remove_class("-active-channel")
        event.button.add_class("-active-channel")
        self._refresh_log()

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
        """Clear all messages (called on disconnect)."""
        self._messages.clear()
        self._channels = []
        self._refresh_log()
