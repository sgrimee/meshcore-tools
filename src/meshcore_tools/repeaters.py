"""RepeatersTab — companion repeater management widget."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.markup import escape as markup_escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static, TabPane

if TYPE_CHECKING:
    from meshcore_tools.companion import CompanionManager


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


class _CmdScreen(ModalScreen[str | None]):
    """Modal prompt for free-text repeater command."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Send command[/bold]", markup=True)
            yield Label("Command:")
            yield Input(placeholder="e.g. uptime", id="cmd")
            with Horizontal():
                yield Button("Send", variant="primary", id="btn_ok")
                yield Button("Cancel", id="btn_cancel")

    def on_mount(self) -> None:
        self.query_one("#cmd", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        elif event.button.id == "btn_ok":
            self.dismiss(self.query_one("#cmd", Input).value)

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.dismiss(self.query_one("#cmd", Input).value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class RepeatersTab(TabPane):
    """Repeater management: list on left, commands + output log on right."""

    DEFAULT_CSS = """
    RepeatersTab {
        height: 1fr;
        layout: horizontal;
    }
    RepeatersTab #repeater_list {
        width: 20;
        height: 1fr;
        border-right: solid $accent;
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
    RepeatersTab #output_log {
        height: 1fr;
        padding: 1 2;
    }
    """

    def __init__(self) -> None:
        super().__init__("F3 Repeaters", id="tab_repeaters")
        self._repeaters: list[dict] = []
        self._selected_idx: int | None = None
        self._log_lines: list[str] = []

    def compose(self) -> ComposeResult:
        yield ListView(id="repeater_list")
        with Container(id="right_pane"):
            with Container(id="cmd_buttons"):
                yield Button("Status", id="btn_status")
                yield Button("Login", id="btn_login")
                yield Button("Cmd", id="btn_cmd")
                yield Button("Trace", id="btn_trace")
                yield Button("Reboot", variant="error", id="btn_reboot")
            with VerticalScroll(id="output_log"):
                yield Static("", id="output_content", markup=True)

    def populate_repeaters(self, contacts: list[dict]) -> None:
        """Called by MeshCoreApp to fill the repeater list from contacts."""
        self._repeaters = [
            c for c in contacts
            if "repeater" in str(c.get("type", "")).lower()
            or "repeater" in str(c.get("role", "")).lower()
        ]
        list_view = self.query_one("#repeater_list", ListView)
        list_view.clear()
        for r in self._repeaters:
            name = r.get("name") or r.get("adv_name") or r.get("public_key", "?")[:8]
            list_view.append(ListItem(Label(name)))
        if self._repeaters:
            self._selected_idx = 0

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        self._selected_idx = event.list_view.index

    def _selected_contact(self) -> dict | None:
        if self._selected_idx is None or self._selected_idx >= len(self._repeaters):
            return None
        return self._repeaters[self._selected_idx]

    def _log(self, line: str) -> None:
        ts = datetime.now(timezone.utc).astimezone().strftime("%H:%M")
        self._log_lines.append(f"[dim]{ts}[/dim]  {line}")
        self.query_one("#output_content", Static).update("\n".join(self._log_lines))
        self.query_one("#output_log", VerticalScroll).scroll_end(animate=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        contact = self._selected_contact()
        if contact is None:
            self._log("[red]No repeater selected[/red]")
            return
        if event.button.id == "btn_status":
            self._run_status(contact)
        elif event.button.id == "btn_login":
            self.app.push_screen(_PasswordScreen(), lambda pwd: self._run_login(contact, pwd))
        elif event.button.id == "btn_cmd":
            self.app.push_screen(_CmdScreen(), lambda cmd: self._run_cmd(contact, cmd))
        elif event.button.id == "btn_trace":
            self._run_trace(contact)
        elif event.button.id == "btn_reboot":
            self._run_reboot(contact)

    @work(thread=False, exclusive=False)
    async def _run_status(self, contact: dict) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("[red]Companion not connected[/red]")
            return
        self._log(f"status → {markup_escape(contact.get('name', '?'))} …")
        result = await manager.send_repeater_status(contact)
        self._log(f"status: {markup_escape(result)}")

    def _run_login(self, contact: dict, pwd: str | None) -> None:
        if not pwd:
            return
        self._do_login(contact, pwd)

    @work(thread=False, exclusive=False)
    async def _do_login(self, contact: dict, pwd: str) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("[red]Companion not connected[/red]")
            return
        self._log(f"login → {markup_escape(contact.get('name', '?'))} …")
        result = await manager.send_repeater_login(contact, pwd)
        self._log(f"login: {markup_escape(result)}")

    def _run_cmd(self, contact: dict, cmd: str | None) -> None:
        if not cmd:
            return
        self._do_cmd(contact, cmd)

    @work(thread=False, exclusive=False)
    async def _do_cmd(self, contact: dict, cmd: str) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("[red]Companion not connected[/red]")
            return
        self._log(f"cmd {markup_escape(cmd)!r} → {markup_escape(contact.get('name', '?'))} …")
        result = await manager.send_repeater_cmd(contact, cmd)
        self._log(f"result: {markup_escape(result)}")

    @work(thread=False, exclusive=False)
    async def _run_trace(self, contact: dict) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("[red]Companion not connected[/red]")
            return
        self._log(f"trace → {markup_escape(contact.get('name', '?'))} …")
        result = await manager.send_repeater_trace(contact)
        self._log(f"trace: {markup_escape(result)}")

    def _run_reboot(self, contact: dict) -> None:
        from textual.app import ComposeResult as _CR

        class _ConfirmReboot(ModalScreen[bool]):
            BINDINGS = [Binding("escape", "cancel", "Cancel")]

            def compose(self) -> _CR:
                with Container():
                    yield Static(
                        f"[bold]Reboot {markup_escape(contact.get('name', '?'))}?[/bold]",
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
        self._log(f"reboot → {markup_escape(contact.get('name', '?'))} …")
        result = await manager.send_repeater_reboot(contact)
        self._log(f"reboot: {markup_escape(result)}")

    def clear(self) -> None:
        """Clear log and repeater list (called on disconnect)."""
        self._repeaters = []
        self._selected_idx = None
        self._log_lines = []
        self.query_one("#repeater_list", ListView).clear()
        self.query_one("#output_content", Static).update("")
