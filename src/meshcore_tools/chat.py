"""ChatTab — companion channel messaging widget."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.markup import escape as markup_escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, SelectionList, Static, TabPane

if TYPE_CHECKING:
    from meshcore_tools.companion import CompanionManager

_MAX_MSG_LEN = 133
_MAX_COMPANION_CHANNELS = 8


class _ImportChannelsScreen(ModalScreen[list[tuple[str, bytes]] | None]):
    """Modal: choose which channels from channels.txt to push to the companion."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    _ImportChannelsScreen {
        align: center middle;
    }
    _ImportChannelsScreen > Container {
        width: 60;
        height: auto;
        max-height: 80%;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    _ImportChannelsScreen SelectionList {
        height: auto;
        max-height: 20;
        border: solid $panel;
        margin-bottom: 1;
    }
    _ImportChannelsScreen Horizontal {
        height: 3;
    }
    _ImportChannelsScreen Button {
        margin-right: 1;
    }
    """

    def __init__(self, channels: list[tuple[str, bytes]]) -> None:
        super().__init__()
        self._channels = channels

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Import channels to companion[/bold]", markup=True)
            yield Static(
                "Select channels to write to the companion device:",
                markup=True,
            )
            yield SelectionList(
                *[(name, i, True) for i, (name, _) in enumerate(self._channels)],
                id="channel_selection",
            )
            with Horizontal():
                yield Button("Import", variant="primary", id="btn_ok")
                yield Button("Cancel", id="btn_cancel")

    def on_mount(self) -> None:
        self.query_one("#channel_selection", SelectionList).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        elif event.button.id == "btn_ok":
            sel = self.query_one("#channel_selection", SelectionList)
            selected_indices = list(sel.selected)
            self.dismiss([self._channels[i] for i in selected_indices])

    def action_cancel(self) -> None:
        self.dismiss(None)


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
    ChatTab #left_pane {
        width: 20;
        height: 1fr;
        layout: vertical;
        border-right: solid $accent;
    }
    ChatTab #channel_list {
        width: 1fr;
        height: 1fr;
    }
    ChatTab #btn_import_channels {
        width: 1fr;
        height: 3;
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
    ChatTab #channel_list ListItem.has-unread Label {
        text-style: bold;
        color: $warning;
    }
    """

    def __init__(self) -> None:
        super().__init__("F2 Channels", id="tab_chat")
        self._channels: list[dict] = []
        self._active_channel_idx: int = 0
        self._messages: dict[int, list[dict]] = {}
        self._unread: dict[int, int] = {}  # channel_idx → unread count

    def compose(self) -> ComposeResult:
        with Container(id="left_pane"):
            yield ListView(id="channel_list")
            yield Button("Import channels", id="btn_import_channels")
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

    def _channel_label(self, ch: dict) -> str:
        """Return the display label for a channel, including unread count if any."""
        count = self._unread.get(ch["idx"], 0)
        if count:
            return f"{ch['name']}  [{count}]"
        return ch["name"]

    def _refresh_channel_item(self, channel_idx: int) -> None:
        """Update a single channel list item's label and CSS class."""
        idxs = [ch["idx"] for ch in self._channels]
        if channel_idx not in idxs:
            return
        pos = idxs.index(channel_idx)
        ch = self._channels[pos]
        list_view = self.query_one("#channel_list", ListView)
        items = list(list_view.query(ListItem))
        if pos < len(items):
            items[pos].query_one(Label).update(self._channel_label(ch))
            if self._unread.get(channel_idx, 0) > 0:
                items[pos].add_class("has-unread")
            else:
                items[pos].remove_class("has-unread")

    def unread_count(self) -> int:
        """Total unread messages across all channels."""
        return sum(self._unread.values())

    def populate_channels(self, channels: list[dict]) -> None:
        """Called by MeshCoreApp after channels are fetched from the device."""
        self._channels = channels
        self._unread.clear()
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
            channel_idx = self._channels[idx]["idx"]
            had_unread = channel_idx in self._unread
            self._unread.pop(channel_idx, None)
            if had_unread:
                self._refresh_channel_item(channel_idx)
                getattr(self.app, "_update_tab_labels", lambda: None)()
            self._active_channel_idx = channel_idx
            self._refresh_log()

    def _select_channel(self, channel_idx: int) -> None:
        had_unread = channel_idx in self._unread
        self._unread.pop(channel_idx, None)
        self._active_channel_idx = channel_idx
        idxs = [ch["idx"] for ch in self._channels]
        if channel_idx in idxs:
            list_view = self.query_one("#channel_list", ListView)
            list_view.index = idxs.index(channel_idx)
            if had_unread:
                self._refresh_channel_item(channel_idx)
        if had_unread:
            getattr(self.app, "_update_tab_labels", lambda: None)()
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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_import_channels":
            self._action_import_channels()

    def _action_import_channels(self) -> None:
        """Compute the diff vs channels.txt and open the import modal."""
        companion: CompanionManager | None = getattr(self.app, "companion", None)
        if companion is None or not companion.is_connected:
            self.app.notify("Companion not connected", severity="warning")
            return

        channels_path: str | None = getattr(self.app, "_channels_path", None)
        if not channels_path:
            self.app.notify(
                "No channels file configured (use --channels option)", severity="warning"
            )
            return

        from meshcore_tools.channels import load_channels

        txt_channels = load_channels(channels_path)
        if not txt_channels:
            self.app.notify("No channels found in channels.txt", severity="warning")
            return

        companion_names = {ch["name"].lower() for ch in self._channels}
        new_channels = [
            (name, key) for name, key in txt_channels if name.lower() not in companion_names
        ]

        if not new_channels:
            self.app.notify("All channels from channels.txt are already on the companion")
            return

        available_slots = _MAX_COMPANION_CHANNELS - len(self._channels)
        if available_slots <= 0:
            self.app.notify(
                "All 8 companion channel slots are occupied", severity="warning"
            )
            return

        if len(new_channels) > available_slots:
            self.app.notify(
                f"Only {available_slots} slot(s) available; "
                f"showing first {available_slots} channel(s)",
                severity="warning",
            )
            new_channels = new_channels[:available_slots]

        self.app.push_screen(
            _ImportChannelsScreen(new_channels),
            self._on_import_confirmed,
        )

    def _on_import_confirmed(
        self, selected: list[tuple[str, bytes]] | None
    ) -> None:
        if not selected:
            return
        self._do_import(selected)

    @work(thread=False, exclusive=False)
    async def _do_import(self, channels_to_import: list[tuple[str, bytes]]) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if manager is None:
            self.app.notify("Companion not connected", severity="error")
            return

        next_slot = max((ch["idx"] for ch in self._channels), default=-1) + 1
        errors: list[str] = []
        imported = 0

        for name, secret in channels_to_import:
            result = await manager.set_channel(next_slot, name, secret)
            if result == "ok":
                imported += 1
                next_slot += 1
            else:
                errors.append(f"{name}: {result}")

        if errors:
            self.app.notify(
                f"Import errors: {'; '.join(errors)}", severity="error", timeout=8
            )
        if imported:
            self.app.notify(f"Imported {imported} channel(s)")
            await manager.fetch_channels()

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
        else:
            self._unread[channel_idx] = self._unread.get(channel_idx, 0) + 1
            self._refresh_channel_item(channel_idx)

    def clear(self) -> None:
        """Clear all messages and channels (called on disconnect)."""
        self._messages.clear()
        self._unread.clear()
        self._active_channel_idx = 0
        self._refresh_log()
        self.populate_channels([])
