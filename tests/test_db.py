"""Tests for lma.db."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from lma.db import load_db, parse_input_file, save_db, update


INPUT_CONTENT = """\
sg-t1000-2                       CLI   6766f573d2ec  Flood
1→Nils-echo                      CLI   5ab07f54cd13  Flood
gw-charly                        CLI   7d1e1ad2a470c8f3a1b2c3d4e5f60708090a0b0c0d0e0f101112131415161718
bad-line
short
"""


def test_parse_input_file_basic(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text(INPUT_CONTENT)
    nodes = parse_input_file(f)
    assert "6766f573d2ec" in nodes
    assert nodes["6766f573d2ec"]["name"] == "sg-t1000-2"
    assert nodes["6766f573d2ec"]["type"] == "CLI"
    assert nodes["6766f573d2ec"]["routing"] == "Flood"
    assert nodes["6766f573d2ec"]["key_complete"] is False


def test_parse_input_file_strips_line_number(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text(INPUT_CONTENT)
    nodes = parse_input_file(f)
    assert "5ab07f54cd13" in nodes
    assert nodes["5ab07f54cd13"]["name"] == "Nils-echo"


def test_parse_input_file_full_key(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text(INPUT_CONTENT)
    nodes = parse_input_file(f)
    full_key = "7d1e1ad2a470c8f3a1b2c3d4e5f60708090a0b0c0d0e0f101112131415161718"
    assert nodes[full_key]["key_complete"] is True


def test_parse_input_file_source_is_filename(tmp_path):
    f = tmp_path / "sam.txt"
    f.write_text("mynode CLI aabbccdd Flood\n")
    nodes = parse_input_file(f)
    assert nodes["aabbccdd"]["source"] == "sam.txt"


def test_load_db_missing_file(tmp_path):
    with patch("lma.db.DB_FILE", tmp_path / "nodes.json"):
        db = load_db()
    assert db == {"nodes": {}}


def test_load_db_reads_existing(tmp_path):
    db_file = tmp_path / "nodes.json"
    db_file.write_text(json.dumps({"nodes": {"aabb": {"name": "x"}}}))
    with patch("lma.db.DB_FILE", db_file):
        db = load_db()
    assert db["nodes"]["aabb"]["name"] == "x"


def test_save_db_roundtrip(tmp_path):
    db_file = tmp_path / "nodes.json"
    db = {"nodes": {"aabb": {"name": "y", "type": "CLI"}}}
    with patch("lma.db.DB_FILE", db_file):
        save_db(db)
        loaded = load_db()
    assert loaded == db


def test_update_merge_partial_key(tmp_path):
    """Partial key from input file gets replaced by full key from API, preserving type/routing."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "test.txt").write_text("my-node REP aabbccdd Flood\n")

    full_key = "aabbccdd" + "0" * 56
    api_nodes = {full_key: {"name": "api-name", "type": "CLI", "source": "api:LUX", "key_complete": True, "last_seen": "2026-01-01"}}

    db_file = tmp_path / "nodes.json"

    with patch("lma.db.INPUT_DIR", input_dir), \
         patch("lma.db.DB_FILE", db_file), \
         patch("lma.db.fetch_nodes", return_value=api_nodes):
        update("LUX")

    db = json.loads(db_file.read_text())
    assert full_key in db["nodes"]
    assert "aabbccdd" not in db["nodes"]
    # type and routing from input file preserved
    assert db["nodes"][full_key]["type"] == "REP"
    assert db["nodes"][full_key]["routing"] == "Flood"
    # last_seen from API preserved
    assert db["nodes"][full_key]["last_seen"] == "2026-01-01"


def test_update_api_failure_continues(tmp_path):
    """API failure is non-fatal; input file nodes still saved."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "test.txt").write_text("my-node CLI aabbccdd\n")
    db_file = tmp_path / "nodes.json"

    with patch("lma.db.INPUT_DIR", input_dir), \
         patch("lma.db.DB_FILE", db_file), \
         patch("lma.db.fetch_nodes", side_effect=Exception("network error")):
        update("LUX")

    db = json.loads(db_file.read_text())
    assert "aabbccdd" in db["nodes"]
