"""Tests for MonitorTab widget instantiation."""

from unittest.mock import MagicMock

from meshcore_tools.monitor import MonitorTab


def _make_provider():
    p = MagicMock()
    p.fetch_packets.return_value = []
    return p


def test_monitor_tab_init_does_not_shadow_widget_region():
    """MonitorTab.__init__ must not assign to self.region (read-only Widget property)."""
    tab = MonitorTab(region="LUX", packet_provider=_make_provider())
    # Widget.region is a read-only property returning a Region object.
    # Our region string must be stored as _region, not region.
    assert tab._region == "LUX"
    # Confirm the public .region attribute is NOT a plain string
    # (it would be if the bug were reintroduced).
    assert not isinstance(tab.region, str), (
        "MonitorTab.region is a string — self.region = region was reintroduced, "
        "which shadows Textual's Widget.region property and causes AttributeError at runtime."
    )


def test_monitor_tab_accepts_poll_interval():
    tab = MonitorTab(region="EU", packet_provider=_make_provider(), poll_interval=10)
    assert tab._region == "EU"
    assert tab.poll_interval == 10
