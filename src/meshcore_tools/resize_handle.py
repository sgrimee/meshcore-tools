"""ResizeHandle — a draggable 1-cell widget for resizing adjacent panels."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from textual.events import MouseDown, MouseMove, MouseUp
from textual.widget import Widget

if TYPE_CHECKING:
    pass


class ResizeHandle(Widget):
    """Drag handle that resizes a target widget.

    Orientation is detected from the handle's own rendered size:
    - width == 1  → vertical handle, dragging left/right changes target width
    - height == 1 → horizontal handle, dragging up/down changes target height

    Size CSS (width/height) must be set by the parent widget's stylesheet.
    """

    DEFAULT_CSS = """
    ResizeHandle {
        background: $accent 15%;
    }
    ResizeHandle:hover {
        background: $accent 50%;
    }
    """

    def __init__(
        self,
        target_getter: Callable[[], Widget],
        min_size: int = 4,
        max_size: int = 120,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._target_getter = target_getter
        self._min_size = min_size
        self._max_size = max_size
        self._dragging = False
        self._vertical = False
        self._start_pos = 0
        self._start_size = 0

    def on_mouse_down(self, event: MouseDown) -> None:
        target = self._target_getter()
        # Detect orientation from actual rendered size
        self._vertical = self.size.width <= 1
        if self._vertical:
            self._start_pos = event.screen_x
            w = target.styles.width
            self._start_size = int(w.value) if w else self._min_size
        else:
            self._start_pos = event.screen_y
            h = target.styles.height
            self._start_size = int(h.value) if h else self._min_size
        self._dragging = True
        self.capture_mouse()
        event.stop()

    def on_mouse_move(self, event: MouseMove) -> None:
        if not self._dragging:
            return
        target = self._target_getter()
        if self._vertical:
            delta = self._start_pos - event.screen_x
            new_size = max(self._min_size, min(self._max_size, self._start_size + delta))
            target.styles.width = new_size
        else:
            delta = self._start_pos - event.screen_y
            new_size = max(self._min_size, min(self._max_size, self._start_size + delta))
            target.styles.height = new_size
        event.stop()

    def on_mouse_up(self, event: MouseUp) -> None:
        self._dragging = False
        self.release_mouse()
        event.stop()
