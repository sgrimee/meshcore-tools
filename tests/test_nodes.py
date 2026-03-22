"""Tests for lma.nodes."""

import pytest
from unittest.mock import patch

from lma.nodes import list_nodes, lookup


DB_FIXTURE = {
    "nodes": {
        "aabbccdd" + "0" * 56: {"name": "alpha-node", "type": "CLI", "routing": "Flood", "key_complete": True, "source": "test.txt"},
        "1122334455667788" + "0" * 48: {"name": "beta-node", "type": "REP", "routing": "", "key_complete": True, "source": "api:LUX", "last_seen": "2026-03-01T10:00:00Z"},
        "ffee": {"name": "partial-node", "type": "CLI", "routing": "", "key_complete": False, "source": "test.txt"},
    }
}


@patch("lma.nodes.load_db", return_value=DB_FIXTURE)
def test_lookup_finds_match(mock_db, capsys):
    lookup("aabb")
    out = capsys.readouterr().out
    assert "alpha-node" in out


@patch("lma.nodes.load_db", return_value=DB_FIXTURE)
def test_lookup_partial_key_indicator(mock_db, capsys):
    lookup("ffee")
    out = capsys.readouterr().out
    assert "[partial key]" in out


@patch("lma.nodes.load_db", return_value=DB_FIXTURE)
def test_lookup_last_seen_shown(mock_db, capsys):
    lookup("1122")
    out = capsys.readouterr().out
    assert "2026-03-01" in out


@patch("lma.nodes.load_db", return_value=DB_FIXTURE)
def test_lookup_no_match_exits(mock_db):
    with pytest.raises(SystemExit) as exc:
        lookup("dead")
    assert exc.value.code == 1


@patch("lma.nodes.load_db", return_value=DB_FIXTURE)
def test_lookup_invalid_prefix_exits(mock_db):
    with pytest.raises(SystemExit) as exc:
        lookup("notHex!")
    assert exc.value.code == 1


@patch("lma.nodes.load_db", return_value=DB_FIXTURE)
def test_list_nodes_sorted_by_name(mock_db, capsys):
    list_nodes()
    out = capsys.readouterr().out
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith("\n")]
    names = [l.split()[0] for l in lines if not l.startswith("3")]
    assert names.index("alpha-node") < names.index("beta-node")
    assert names.index("beta-node") < names.index("partial-node")


@patch("lma.nodes.load_db", return_value=DB_FIXTURE)
def test_list_nodes_by_key(mock_db, capsys):
    list_nodes(by_key=True)
    out = capsys.readouterr().out
    # Keys: 1122... < aabb... < ffee... — check ffee appears after aabb
    pos_aabb = out.index("alpha-node")
    pos_ffee = out.index("partial-node")
    assert pos_aabb < pos_ffee


@patch("lma.nodes.load_db", return_value=DB_FIXTURE)
def test_list_nodes_partial_key_marked(mock_db, capsys):
    list_nodes()
    out = capsys.readouterr().out
    # partial-node should have '*' marker, others ' '
    for line in out.splitlines():
        if "partial-node" in line:
            assert "*" in line
        elif "alpha-node" in line or "beta-node" in line:
            assert " " in line  # space marker for complete keys


@patch("lma.nodes.load_db", return_value={"nodes": {}})
def test_list_nodes_empty_db(mock_db, capsys):
    list_nodes()
    out = capsys.readouterr().out
    assert "lma nodes update" in out
