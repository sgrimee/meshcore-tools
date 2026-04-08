"""Tests for MonitorTab widget instantiation and multi-observer grouping."""

from unittest.mock import MagicMock

from meshcore_tools.monitor import MonitorTab, _build_detail_text


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


def test_monitor_tab_poll_worker_uses_app_call_from_thread():
    """_poll_worker must use self.app.call_from_thread, not self.call_from_thread.

    TabPane (Widget) has no call_from_thread — that method lives on App.
    This test catches the regression by verifying the source code directly.
    """
    import inspect
    from meshcore_tools.monitor import MonitorTab
    src = inspect.getsource(MonitorTab._poll_worker)
    assert "self.app.call_from_thread" in src, (
        "_poll_worker uses self.call_from_thread instead of self.app.call_from_thread; "
        "TabPane does not have call_from_thread and will raise AttributeError at runtime."
    )
    assert "self.call_from_thread(" not in src.replace("self.app.call_from_thread(", ""), (
        "_poll_worker has a bare self.call_from_thread() call — must be self.app.call_from_thread()."
    )


# ---------------------------------------------------------------------------
# Multi-observer grouping
# ---------------------------------------------------------------------------

def _make_packet(pid: str, origin_id: str = "AABBCC", origin: str = "obs-a",
                 snr: float | None = 5.0, rssi: int | None = -90) -> dict:
    """Minimal packet dict as returned by a provider."""
    return {
        "id": pid,
        "regions": ["LUX"],
        "raw_data": "",
        "origin_id": origin_id,
        "origin": origin,
        "snr": snr,
        "rssi": rssi,
        "heard_at": "2026-04-08T10:00:00Z",
    }


def _tab_no_ui() -> MonitorTab:
    """MonitorTab with _rebuild_table and _set_status stubbed out (no widget tree needed)."""
    tab = MonitorTab(region="LUX", packet_provider=_make_provider())
    tab._rebuild_table = MagicMock()  # type: ignore[method-assign]
    tab._set_status = MagicMock()  # type: ignore[method-assign]
    tab._detail_panel_open = False
    return tab


def test_ingest_initialises_observers_list():
    """First ingest of a packet creates _observers with one rich entry (includes path fields)."""
    tab = _tab_no_ui()
    p = _make_packet("hash1", origin_id="AABBCC", origin="obs-a")
    tab._ingest_packets([p])
    assert len(tab._packets_by_id["hash1"]["_observers"]) == 1
    obs = tab._packets_by_id["hash1"]["_observers"][0]
    assert obs["origin_id"] == "AABBCC"
    assert obs["origin"] == "obs-a"
    # Observer dict must include decoded path fields for sub-row rendering.
    assert "_path" in obs
    assert "_decoded" in obs
    assert "_route_type" in obs


def test_ingest_duplicate_accumulates_observers():
    """A second packet with the same id appends an observer entry, does not add a new row."""
    tab = _tab_no_ui()
    p1 = _make_packet("hash1", origin_id="AABB", origin="obs-a", snr=5.0, rssi=-90)
    p2 = _make_packet("hash1", origin_id="CCDD", origin="obs-b", snr=3.0, rssi=-100)
    tab._ingest_packets([p1])
    tab._ingest_packets([p2])
    stored = tab._packets_by_id["hash1"]
    assert len(stored["_observers"]) == 2
    assert stored["_observers"][1]["origin_id"] == "CCDD"
    # Only one entry in _all_packets
    assert sum(1 for p in tab._all_packets if p["id"] == "hash1") == 1


def test_ingest_duplicate_does_not_add_to_seen_ids_twice():
    """_seen_ids stays consistent after duplicate ingest."""
    tab = _tab_no_ui()
    p1 = _make_packet("hash1")
    p2 = _make_packet("hash1", origin_id="ZZZZ", origin="obs-b")
    tab._ingest_packets([p1, p2])
    assert "hash1" in tab._seen_ids
    # Still only one row
    assert len(tab._all_packets) == 1


# ---------------------------------------------------------------------------
# _build_detail_text — Observers section
# ---------------------------------------------------------------------------

def _make_ingested_packet(n_observers: int = 1) -> dict:
    """Return a packet dict as it exists after _ingest_packets processing."""
    observers = [
        {"origin_id": f"OBS{i:04X}", "origin": f"obs-{i}", "snr": float(5 - i),
         "rssi": -90 - i * 5, "heard_at": f"2026-04-08T10:00:0{i}Z"}
        for i in range(n_observers)
    ]
    return {
        "id": "deadbeef",
        "regions": ["LUX"],
        "raw_data": "",
        "origin_id": observers[0]["origin_id"],
        "origin": observers[0]["origin"],
        "snr": observers[0]["snr"],
        "rssi": observers[0]["rssi"],
        "heard_at": observers[0]["heard_at"],
        "_observers": observers,
        "_decoded": {},
        "_path": [],
        "_src_hash": "",
        "_route_type": "",
        "_path_hop_size": 1,
        "payload_type": "Advert",
    }


def test_build_detail_no_observers_section_for_single_observer():
    p = _make_ingested_packet(1)
    text = _build_detail_text(p, {})
    assert "Observers" not in text


def test_build_detail_shows_observers_section_for_multiple():
    p = _make_ingested_packet(3)
    text = _build_detail_text(p, {})
    assert "Observers" in text
    assert "obs-0" in text
    assert "obs-1" in text
    assert "obs-2" in text


def test_build_detail_marks_primary_observer():
    p = _make_ingested_packet(2)
    text = _build_detail_text(p, {})
    assert "(primary)" in text


# ---------------------------------------------------------------------------
# _observer_view / _view_for_key
# ---------------------------------------------------------------------------

def _tab_with_two_obs() -> MonitorTab:
    """Tab with one packet that has two observer records."""
    tab = _tab_no_ui()
    p1 = _make_packet("hash1", origin_id="AA", origin="obs-a", snr=5.0, rssi=-90)
    p2 = _make_packet("hash1", origin_id="BB", origin="obs-b", snr=2.0, rssi=-105)
    tab._ingest_packets([p1])
    tab._ingest_packets([p2])
    return tab


def test_observer_view_zero_returns_primary():
    tab = _tab_with_two_obs()
    primary = tab._packets_by_id["hash1"]
    assert tab._observer_view("hash1", 0) is primary


def test_observer_view_one_returns_overlay():
    tab = _tab_with_two_obs()
    view = tab._observer_view("hash1", 1)
    assert view["origin_id"] == "BB"
    assert view["origin"] == "obs-b"
    assert view.get("_observer_index") == 1
    assert view.get("_observer_total") == 2


def test_view_for_key_parent():
    tab = _tab_with_two_obs()
    primary = tab._packets_by_id["hash1"]
    assert tab._view_for_key("hash1") is primary


def test_view_for_key_subrow():
    tab = _tab_with_two_obs()
    view = tab._view_for_key("hash1::1")
    assert view is not None
    assert view["origin_id"] == "BB"


def test_view_for_key_unknown_returns_none():
    tab = _tab_no_ui()
    assert tab._view_for_key("nonexistent") is None
    assert tab._view_for_key("nonexistent::0") is None


# ---------------------------------------------------------------------------
# Expand / collapse (via _row_keys + _expanded)
# ---------------------------------------------------------------------------

def test_on_data_table_row_selected_expands_then_collapses():
    """on_data_table_row_selected toggles _expanded for multi-observer packets."""
    tab = _tab_with_two_obs()
    # Seed _row_keys as if the table had been rendered with just the parent row.
    tab._row_keys = ["hash1"]
    mock_event = MagicMock()
    mock_event.cursor_row = 0
    # First call → expand
    tab.on_data_table_row_selected(mock_event)
    assert "hash1" in tab._expanded
    # Second call → collapse
    tab._row_keys = ["hash1"]
    tab.on_data_table_row_selected(mock_event)
    assert "hash1" not in tab._expanded


def test_on_data_table_row_selected_noop_for_subrow():
    """on_data_table_row_selected does nothing when cursor is on a sub-row."""
    tab = _tab_with_two_obs()
    tab._row_keys = ["hash1", "hash1::1"]
    mock_event = MagicMock()
    mock_event.cursor_row = 1  # sub-row
    tab.on_data_table_row_selected(mock_event)
    assert "hash1" not in tab._expanded


# ---------------------------------------------------------------------------
# _build_detail_text — sub-row "Observation N of M" header
# ---------------------------------------------------------------------------

def test_build_detail_subrow_shows_observation_header():
    p = _make_ingested_packet(3)
    view = dict(p)
    view["_observer_index"] = 1
    view["_observer_total"] = 3
    text = _build_detail_text(view, {})
    assert "Observation 2 of 3" in text
    assert "Observers" not in text
