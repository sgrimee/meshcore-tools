"""ContactsTab — companion contact management widget."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.markup import escape as markup_escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static, TabbedContent, TabPane


if TYPE_CHECKING:
    from meshcore_tools.companion import CompanionManager

# Short badge shown in list next to each contact name
_TYPE_BADGE: dict[int, str] = {0: "???", 1: "CLI", 2: "REP", 3: "RMS", 4: "SNS"}

# Which command buttons are shown for each contact type
_TYPE_CMDS: dict[int, list[str]] = {
    0: [],                                                              # Unknown
    1: ["btn_ping", "btn_telemetry"],                                   # ChatNode
    2: ["btn_ping", "btn_status", "btn_telemetry", "btn_login", "btn_trace", "btn_reboot"],  # Repeater
    3: ["btn_status", "btn_login", "btn_ping"],                         # RoomServer
    4: ["btn_status", "btn_ping", "btn_telemetry"],                     # Sensor
}


class _PasswordScreen(ModalScreen[str | None]):
    """Modal prompt for repeater password."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Repeater login[/bold]", markup=True)
            yield Label("Password:")
            yield Input(password=True, id="pwd")
            with Horizontal():
                yield Button("Login", variant="primary", id="btn_ok")
                yield Button("Cancel", id="btn_cancel")

    def on_mount(self) -> None:
        self.query_one("#pwd", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        elif event.button.id == "btn_ok":
            self.dismiss(self.query_one("#pwd", Input).value)

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.dismiss(self.query_one("#pwd", Input).value)

    def action_cancel(self) -> None:
        self.dismiss(None)


_CMD_IDS = ["btn_ping", "btn_status", "btn_telemetry", "btn_login", "btn_trace", "btn_reboot"]
# (order matches _TYPE_CMDS lists above)


class _CmdButton(Button):
    """Command toolbar button — not individually focusable; navigated with left/right."""

    can_focus = False


class RepeatersTab(TabPane):
    """Contacts tab: list on left, contextual commands + output log on right."""

    BINDINGS = [
        Binding("left", "prev_cmd", "Prev cmd", show=False),
        Binding("right", "next_cmd", "Next cmd", show=False),
        Binding("enter", "run_cmd", "Run cmd", show=False),
    ]

    DEFAULT_CSS = """
    RepeatersTab {
        height: 1fr;
        layout: horizontal;
    }
    RepeatersTab #repeater_list {
        width: 22;
        height: 1fr;
        border-right: solid $accent;
    }
    RepeatersTab #repeater_list .contact-header {
        background: $panel-darken-1;
        color: $accent;
        padding: 0 1;
        text-style: bold;
        border-top: solid $panel-lighten-1;
    }
    RepeatersTab #right_pane {
        width: 1fr;
        height: 1fr;
        layout: vertical;
    }
    RepeatersTab #cmd_buttons {
        height: 3;
        layout: horizontal;
        padding: 0 1;
        background: $panel;
    }
    RepeatersTab #cmd_buttons Button {
        margin-right: 1;
    }
    RepeatersTab #cmd_buttons Button.-active-cmd {
        border: solid $accent;
    }
    RepeatersTab #output_log {
        height: 1fr;
        padding: 1 2;
    }
    RepeatersTab #input_bar {
        height: 3;
        padding: 0 1;
        background: $panel;
    }
    """

    def __init__(self) -> None:
        super().__init__("F3 Contacts", id="tab_repeaters")
        self._repeaters: list[dict] = []
        self._list_item_map: list[int | None] = []  # list position → _repeaters index (None = header)
        self._selected_idx: int | None = None
        self._log_lines: list[str] = []
        self._active_cmd_idx: int = 0
        self._tab_active: bool = False

    def compose(self) -> ComposeResult:
        yield ListView(id="repeater_list")
        with Container(id="right_pane"):
            with Container(id="cmd_buttons"):
                yield _CmdButton("Ping", id="btn_ping")
                yield _CmdButton("Status", id="btn_status")
                yield _CmdButton("Telemetry", id="btn_telemetry")
                yield _CmdButton("Login", id="btn_login")
                yield _CmdButton("Trace", id="btn_trace")
                yield _CmdButton("Reboot", variant="error", id="btn_reboot")
            with VerticalScroll(id="output_log"):
                yield Static("", id="output_content", markup=True)
            yield Input(placeholder="DM text  or  /command", id="input_bar")

    def on_mount(self) -> None:
        self._update_cmd_visibility()

    def _update_cmd_visibility(self) -> None:
        """Show/hide command buttons based on the selected contact's type."""
        contact = self._selected_contact()
        ctype = contact.get("type", 0) if contact else 0
        visible = set(_TYPE_CMDS.get(ctype, []))
        for btn_id in _CMD_IDS:
            try:
                self.query_one(f"#{btn_id}", Button).display = btn_id in visible
            except Exception:
                pass
        # Clamp active cmd index to visible buttons
        visible_ids = _TYPE_CMDS.get(ctype, [])
        if visible_ids:
            self._active_cmd_idx = min(self._active_cmd_idx, len(visible_ids) - 1)
        self._highlight_active_cmd()

    def _highlight_active_cmd(self) -> None:
        contact = self._selected_contact()
        ctype = contact.get("type", 0) if contact else 0
        visible_ids = _TYPE_CMDS.get(ctype, [])
        for i, btn_id in enumerate(visible_ids):
            try:
                self.query_one(f"#{btn_id}", Button).set_class(
                    self._tab_active and i == self._active_cmd_idx, "-active-cmd"
                )
            except Exception:
                pass

    def on_tabbed_content_tab_activated(
        self, event: "TabbedContent.TabActivated"
    ) -> None:
        self._tab_active = event.pane is self
        self._highlight_active_cmd()

    def action_prev_cmd(self) -> None:
        contact = self._selected_contact()
        ctype = contact.get("type", 0) if contact else 0
        visible_ids = _TYPE_CMDS.get(ctype, [])
        if not visible_ids:
            return
        self._active_cmd_idx = (self._active_cmd_idx - 1) % len(visible_ids)
        self._highlight_active_cmd()

    def action_next_cmd(self) -> None:
        contact = self._selected_contact()
        ctype = contact.get("type", 0) if contact else 0
        visible_ids = _TYPE_CMDS.get(ctype, [])
        if not visible_ids:
            return
        self._active_cmd_idx = (self._active_cmd_idx + 1) % len(visible_ids)
        self._highlight_active_cmd()

    def action_run_cmd(self) -> None:
        contact = self._selected_contact()
        ctype = contact.get("type", 0) if contact else 0
        visible_ids = _TYPE_CMDS.get(ctype, [])
        if not visible_ids:
            return
        try:
            self.query_one(f"#{visible_ids[self._active_cmd_idx]}", Button).press()
        except Exception:
            pass

    # Display order for contact type groups
    _TYPE_ORDER = [1, 2, 3, 4, 0]
    _TYPE_LABEL = {0: "Unknown", 1: "CLI", 2: "Repeaters", 3: "Room Servers", 4: "Sensors"}

    def populate_repeaters(self, contacts: list[dict]) -> None:
        """Called by MeshCoreApp to fill the contact list, grouped by type."""
        self._repeaters = contacts
        self._list_item_map = []
        self._selected_idx = None
        list_view = self.query_one("#repeater_list", ListView)
        list_view.clear()

        # Group contacts by type
        groups: dict[int, list[tuple[int, dict]]] = {}
        for i, r in enumerate(self._repeaters):
            ctype = r.get("type", 0)
            groups.setdefault(ctype, []).append((i, r))

        for ctype in self._TYPE_ORDER:
            members = groups.get(ctype, [])
            if not members:
                continue
            # Header row
            header = ListItem(Label(f" {self._TYPE_LABEL.get(ctype, '?')} "))
            header.add_class("contact-header")
            list_view.append(header)
            self._list_item_map.append(None)
            # Contact rows
            for i, r in members:
                name = r.get("adv_name") or r.get("name") or r.get("public_key", "?")[:8]
                list_view.append(ListItem(Label(f"  {name}")))
                self._list_item_map.append(i)
                if self._selected_idx is None:
                    self._selected_idx = i

        # Highlight the first selectable (non-header) row
        first_selectable = next(
            (i for i, v in enumerate(self._list_item_map) if v is not None), None
        )
        if first_selectable is not None:
            list_view.index = first_selectable
        self._update_cmd_visibility()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        pos = event.list_view.index
        if pos is None or pos >= len(self._list_item_map):
            return
        contact_idx = self._list_item_map[pos]
        if contact_idx is None:
            return  # header row — keep current selection
        self._selected_idx = contact_idx
        self._active_cmd_idx = 0
        self._update_cmd_visibility()

    def _selected_contact(self) -> dict | None:
        if self._selected_idx is None or self._selected_idx >= len(self._repeaters):
            return None
        return self._repeaters[self._selected_idx]

    def _log(self, line: str, style: str = "") -> None:
        ts = datetime.now(timezone.utc).astimezone().strftime("%H:%M")
        entry = f"[dim]{ts}[/dim]  {f'[{style}]{line}[/{style}]' if style else line}"
        self._log_lines.append(entry)
        self.query_one("#output_content", Static).update("\n".join(self._log_lines))
        self.query_one("#output_log", VerticalScroll).scroll_end(animate=False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "input_bar":
            return
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        contact = self._selected_contact()
        if contact is None:
            self._log("No contact selected", "red")
            return
        if text.startswith("/"):
            self._do_cmd(contact, text[1:].strip())
        else:
            self._do_dm(contact, text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        contact = self._selected_contact()
        if contact is None:
            self._log("No contact selected", "red")
            return
        if event.button.id == "btn_ping":
            self._run_ping(contact)
        elif event.button.id == "btn_status":
            self._run_status(contact)
        elif event.button.id == "btn_telemetry":
            self._run_telemetry(contact)
        elif event.button.id == "btn_login":
            self.app.push_screen(_PasswordScreen(), lambda pwd: self._run_login(contact, pwd))
        elif event.button.id == "btn_trace":
            self._run_trace(contact)
        elif event.button.id == "btn_reboot":
            self._run_reboot(contact)

    def _contact_name(self, contact: dict) -> str:
        return markup_escape(contact.get("adv_name") or contact.get("name", "?"))

    @work(thread=False, exclusive=False)
    async def _do_dm(self, contact: dict, msg: str) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("Companion not connected", "red")
            return
        self._log(f"→ {self._contact_name(contact)}: {markup_escape(msg)}", "cyan")
        result = await manager.send_contact_msg(contact, msg)
        if result.startswith("error"):
            self._log(f"DM: {markup_escape(result)}", "red")
        else:
            self._log(f"DM: {markup_escape(result)}", "green")

    @work(thread=False, exclusive=False)
    async def _run_ping(self, contact: dict) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("Companion not connected", "red")
            return
        self._log(f"ping → {self._contact_name(contact)} …", "dim")
        result = await manager.send_contact_ping(contact)
        if result in ("timeout", "not connected") or result.startswith("error"):
            self._log(f"ping: {markup_escape(result)}", "red")
        else:
            self._log(f"ping: {markup_escape(result)}", "yellow")

    @work(thread=False, exclusive=False)
    async def _run_telemetry(self, contact: dict) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("Companion not connected", "red")
            return
        self._log(f"telemetry → {self._contact_name(contact)} …", "dim")
        result = await manager.send_contact_telemetry(contact)
        if result in ("timeout", "not connected") or result.startswith("error"):
            self._log(f"telemetry: {markup_escape(result)}", "red")
        else:
            self._log(f"telemetry: {markup_escape(result)}", "yellow")

    def receive_contact_message(
        self, pubkey_prefix: str, sender: str, text: str, timestamp: int
    ) -> None:
        """Show an incoming DM in the output log (called by MeshCoreApp)."""
        self._log(f"[bold]{markup_escape(sender)}:[/bold] {markup_escape(text)}", "green")

    @work(thread=False, exclusive=False)
    async def _run_status(self, contact: dict) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("Companion not connected", "red")
            return
        self._log(f"status → {self._contact_name(contact)} …", "dim")
        result = await manager.send_repeater_status(contact)
        if result in ("timeout", "not connected") or result.startswith("error"):
            self._log(f"status: {markup_escape(result)}", "red")
        else:
            self._log(f"status: {markup_escape(result)}", "yellow")

    def _run_login(self, contact: dict, pwd: str | None) -> None:
        if not pwd:
            return
        self._do_login(contact, pwd)

    @work(thread=False, exclusive=False)
    async def _do_login(self, contact: dict, pwd: str) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("Companion not connected", "red")
            return
        self._log(f"login → {self._contact_name(contact)} …", "dim")
        result = await manager.send_repeater_login(contact, pwd)
        if result.startswith("error"):
            self._log(f"login: {markup_escape(result)}", "red")
        else:
            self._log(f"login: {markup_escape(result)}", "yellow")

    @work(thread=False, exclusive=False)
    async def _do_cmd(self, contact: dict, cmd: str) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("Companion not connected", "red")
            return
        self._log(f"/{markup_escape(cmd)} → {self._contact_name(contact)} …", "cyan")
        result = await manager.send_contact_cmd(contact, cmd)
        if result.startswith("error"):
            self._log(f"cmd: {markup_escape(result)}", "red")
        else:
            self._log(f"cmd: {markup_escape(result)}", "green")

    @work(thread=False, exclusive=False)
    async def _run_trace(self, contact: dict) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("Companion not connected", "red")
            return
        self._log(f"trace → {self._contact_name(contact)} …", "dim")
        result = await manager.send_repeater_trace(contact)
        if result in ("timeout", "not connected") or result.startswith("error"):
            self._log(f"trace: {markup_escape(result)}", "red")
        else:
            self._log(f"trace: {markup_escape(result)}", "yellow")

    def _run_reboot(self, contact: dict) -> None:
        from textual.app import ComposeResult as _CR

        class _ConfirmReboot(ModalScreen[bool]):
            BINDINGS = [Binding("escape", "cancel", "Cancel")]

            def compose(self) -> _CR:
                with Container():
                    yield Static(
                        f"[bold]Reboot {markup_escape(contact.get('adv_name') or contact.get('name', '?'))}?[/bold]",  # noqa: E501
                        markup=True,
                    )
                    with Horizontal():
                        yield Button("Reboot", variant="error", id="btn_yes")
                        yield Button("Cancel", id="btn_no")

            def on_button_pressed(self, event: Button.Pressed) -> None:
                self.dismiss(event.button.id == "btn_yes")

            def action_cancel(self) -> None:
                self.dismiss(False)

        self.app.push_screen(_ConfirmReboot(), lambda confirmed: self._do_reboot(contact, confirmed))

    def _do_reboot(self, contact: dict, confirmed: bool) -> None:
        if not confirmed:
            return
        self._exec_reboot(contact)

    @work(thread=False, exclusive=False)
    async def _exec_reboot(self, contact: dict) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("[red]Companion not connected[/red]")
            return
        self._log(f"reboot → {self._contact_name(contact)} …", "dim")
        result = await manager.send_repeater_reboot(contact)
        if result.startswith("error"):
            self._log(f"reboot: {markup_escape(result)}", "red")
        else:
            self._log(f"reboot: {markup_escape(result)}", "yellow")

    def clear(self) -> None:
        """Clear log and contact list (called on disconnect)."""
        self._repeaters = []
        self._list_item_map = []
        self._selected_idx = None
        self._log_lines = []
        self.query_one("#repeater_list", ListView).clear()
        self.query_one("#output_content", Static).update("")
        self._update_cmd_visibility()
