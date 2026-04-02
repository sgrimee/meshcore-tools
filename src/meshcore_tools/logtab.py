"""Logging panel — live Python log records with a level filter."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Label, RichLog, Select, TabPane
from textual.widget import Widget


_LEVEL_COLORS: dict[int, str] = {
    logging.DEBUG: "dim",
    logging.INFO: "green",
    logging.WARNING: "yellow",
    logging.ERROR: "red",
    logging.CRITICAL: "bold red",
}

_LEVELS: list[tuple[str, int]] = [
    ("DEBUG", logging.DEBUG),
    ("INFO", logging.INFO),
    ("WARNING", logging.WARNING),
    ("ERROR", logging.ERROR),
    ("CRITICAL", logging.CRITICAL),
]


class NewLogRecord(Message):
    """Carries a logging.LogRecord from TuiLogHandler to a log view."""

    def __init__(self, record: logging.LogRecord) -> None:
        super().__init__()
        self.record = record


class TuiLogHandler(logging.Handler):
    """Logging handler that forwards records to one or more LogView widgets.

    post_message() is thread-safe, so this handler is safe to use from any thread
    or coroutine.
    """

    def __init__(self, *targets: "LogView") -> None:
        super().__init__(level=logging.DEBUG)
        self._targets = list(targets)

    def emit(self, record: logging.LogRecord) -> None:
        for target in self._targets:
            try:
                target.post_message(NewLogRecord(record))
            except Exception:
                pass  # logging handlers must never raise


class LogView(Widget):
    """Core log display: level-filter toolbar + scrollable RichLog."""

    DEFAULT_CSS = """
    LogView {
        layout: vertical;
    }
    LogView #log_toolbar {
        height: 3;
        padding: 0 1;
        align: left middle;
    }
    LogView #log_toolbar Label {
        margin-right: 1;
        content-align: left middle;
        height: 3;
    }
    LogView #log_level {
        width: 20;
    }
    LogView RichLog {
        height: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._records: deque[logging.LogRecord] = deque(maxlen=1000)
        self._level: int = logging.INFO

    def compose(self) -> ComposeResult:
        with Horizontal(id="log_toolbar"):
            yield Label("Level:")
            yield Select(
                options=_LEVELS,
                value=logging.INFO,
                id="log_level",
                allow_blank=False,
            )
        yield RichLog(id="log_output", markup=True, highlight=False, auto_scroll=True)

    def on_new_log_record(self, msg: NewLogRecord) -> None:
        self._records.append(msg.record)
        if msg.record.levelno >= self._level:
            self._render_record(msg.record)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "log_level" and event.value is not Select.BLANK:
            self._level = int(event.value)
            self._rebuild()

    def _rebuild(self) -> None:
        log_output = self.query_one(RichLog)
        log_output.clear()
        for record in self._records:
            if record.levelno >= self._level:
                self._render_record(record)

    def _render_record(self, record: logging.LogRecord) -> None:
        log_output = self.query_one(RichLog)
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        color = _LEVEL_COLORS.get(record.levelno, "white")
        # Escape Rich markup characters in user-supplied strings
        msg = record.getMessage().replace("[", "\\[")
        name = record.name.replace("[", "\\[")
        log_output.write(
            f"[dim]{ts}[/] [{color}]{record.levelname:<8}[/] [dim]{name}[/] {msg}"
        )


class LogTab(TabPane):
    """Live log viewer tab — wraps LogView inside a TabbedContent tab."""

    def __init__(self) -> None:
        super().__init__("Logs", id="tab_logs")

    def compose(self) -> ComposeResult:
        yield LogView()


class LogPanel(Widget):
    """Bottom log panel: full-width, always below TabbedContent, toggleable via l."""

    DEFAULT_CSS = """
    LogPanel {
        display: none;
        height: 10;
        border-top: solid $accent;
        layout: vertical;
    }
    LogPanel #log_panel_title {
        height: 1;
        padding: 0 1;
        background: $accent-darken-1;
        color: $text;
        text-style: bold;
    }
    LogPanel LogView {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Logs", id="log_panel_title")
        yield LogView()

