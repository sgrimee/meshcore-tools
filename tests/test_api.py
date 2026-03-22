"""Tests for lma.api."""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from lma.api import ROLE_MAP, fetch_nodes, fetch_packets


NODES_FIXTURE = {
    "nodes": [
        {"public_key": "abcd1234" + "0" * 56, "name": "test-node", "device_role": 2, "last_seen": "2026-01-01T00:00:00Z"},
        {"public_key": "beef5678" + "0" * 56, "name": "cli-node", "device_role": 1, "last_seen": ""},
    ]
}

PACKETS_FIXTURE = {
    "packets": [
        {"id": "p1", "origin_id": "abcd1234", "heard_at": "2026-01-01T12:00:00Z",
         "payload_type": "TEXT_MSG", "snr": 8.5, "rssi": -87, "path": [], "route_type": "FLOOD"},
        {"id": "p2", "origin_id": "beef5678", "heard_at": "2026-01-01T11:00:00Z",
         "payload_type": "POSITION", "snr": 5.0, "rssi": -95, "path": ["relay1"], "route_type": "FLOOD"},
    ]
}


def _mock_urlopen(fixture: dict):
    resp = MagicMock()
    resp.read.return_value = json.dumps(fixture).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


@patch("lma.api.urllib.request.urlopen")
def test_fetch_nodes_parses_role_map(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen(NODES_FIXTURE)
    nodes = fetch_nodes("LUX")
    key1 = "abcd1234" + "0" * 56
    key2 = "beef5678" + "0" * 56
    assert nodes[key1]["type"] == "REP"  # device_role 2
    assert nodes[key2]["type"] == "CLI"  # device_role 1
    assert nodes[key1]["name"] == "test-node"
    assert nodes[key1]["key_complete"] is True
    assert nodes[key1]["source"] == "api:LUX"


@patch("lma.api.urllib.request.urlopen")
def test_fetch_nodes_unknown_role(mock_urlopen):
    fixture = {"nodes": [{"public_key": "aa" * 32, "name": "x", "device_role": 99, "last_seen": ""}]}
    mock_urlopen.return_value = _mock_urlopen(fixture)
    nodes = fetch_nodes("LUX")
    assert nodes["aa" * 32]["type"] == "99"


@patch("lma.api.urllib.request.urlopen")
def test_fetch_packets_returns_list(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen(PACKETS_FIXTURE)
    packets = fetch_packets("LUX", limit=10)
    assert len(packets) == 2
    assert packets[0]["id"] == "p1"
    assert packets[1]["payload_type"] == "POSITION"


@patch("lma.api.urllib.request.urlopen")
def test_fetch_packets_empty(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen({"packets": []})
    packets = fetch_packets("LUX")
    assert packets == []


@patch("lma.api.urllib.request.urlopen")
def test_fetch_packets_top_level_list(mock_urlopen):
    """API may return a bare list instead of {"packets": [...]}."""
    mock_urlopen.return_value = _mock_urlopen(PACKETS_FIXTURE["packets"])
    packets = fetch_packets("LUX")
    assert len(packets) == 2
    assert packets[0]["id"] == "p1"


@patch("lma.api.urllib.request.urlopen")
def test_fetch_nodes_propagates_error(mock_urlopen):
    mock_urlopen.side_effect = Exception("network error")
    with pytest.raises(Exception, match="network error"):
        fetch_nodes("LUX")
