"""Tests for contacts_store.py — contact persistence in contacts.toml."""

from __future__ import annotations

import tomllib

from meshcore_tools.contacts_store import load_contacts, persist_contact


_CONTACT_A = {"public_key": "aabbcc", "adv_name": "repeater-1", "type": 2}
_CONTACT_B = {"public_key": "ddeeff", "adv_name": "node-2", "type": 1}


def test_load_contacts_missing_file(tmp_path):
    assert load_contacts(config_dir=tmp_path) == {}


def test_load_contacts_invalid_toml(tmp_path):
    (tmp_path / "contacts.toml").write_text("not valid ][")
    assert load_contacts(config_dir=tmp_path) == {}


def test_persist_new_contact_returns_true(tmp_path):
    assert persist_contact(_CONTACT_A, config_dir=tmp_path) is True


def test_persist_new_contact_creates_file(tmp_path):
    persist_contact(_CONTACT_A, config_dir=tmp_path)
    assert (tmp_path / "contacts.toml").exists()


def test_persist_existing_contact_returns_false(tmp_path):
    persist_contact(_CONTACT_A, config_dir=tmp_path)
    assert persist_contact(_CONTACT_A, config_dir=tmp_path) is False


def test_load_contacts_roundtrip(tmp_path):
    persist_contact(_CONTACT_A, config_dir=tmp_path)
    contacts = load_contacts(config_dir=tmp_path)
    assert contacts["aabbcc"]["adv_name"] == "repeater-1"
    assert contacts["aabbcc"]["type"] == 2


def test_multiple_contacts_accumulated(tmp_path):
    persist_contact(_CONTACT_A, config_dir=tmp_path)
    persist_contact(_CONTACT_B, config_dir=tmp_path)
    contacts = load_contacts(config_dir=tmp_path)
    assert "aabbcc" in contacts
    assert "ddeeff" in contacts


def test_persist_upserts_name_for_existing_key(tmp_path):
    persist_contact(_CONTACT_A, config_dir=tmp_path)
    updated = {"public_key": "aabbcc", "adv_name": "renamed", "type": 2}
    persist_contact(updated, config_dir=tmp_path)
    contacts = load_contacts(config_dir=tmp_path)
    assert contacts["aabbcc"]["adv_name"] == "renamed"


def test_persist_contact_without_public_key_returns_false(tmp_path):
    assert persist_contact({"adv_name": "no-key", "type": 1}, config_dir=tmp_path) is False


def test_contacts_toml_is_valid_toml(tmp_path):
    persist_contact(_CONTACT_A, config_dir=tmp_path)
    text = (tmp_path / "contacts.toml").read_text()
    data = tomllib.loads(text)
    assert "contacts" in data


def test_contacts_pubkey_not_duplicated_in_value(tmp_path):
    persist_contact(_CONTACT_A, config_dir=tmp_path)
    text = (tmp_path / "contacts.toml").read_text()
    data = tomllib.loads(text)
    stored = data["contacts"]["aabbcc"]
    assert "public_key" not in stored


def test_adv_name_with_special_chars(tmp_path):
    contact = {"public_key": "ff00", "adv_name": 'rep"a\\b', "type": 2}
    persist_contact(contact, config_dir=tmp_path)
    contacts = load_contacts(config_dir=tmp_path)
    assert contacts["ff00"]["adv_name"] == 'rep"a\\b'
