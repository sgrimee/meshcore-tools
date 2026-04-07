"""Tests for companion Textual message classes."""

from meshcore_tools.companion import (
    ChannelMessage,
    CompanionConnected,
    CompanionConnectionError,
    CompanionDisconnected,
    ContactMessage,
    ContactsUpdated,
    _extract_channel_key_hex,
)


def test_companion_connected_fields():
    msg = CompanionConnected(node_name="gw-home", node_key="aabbcc")
    assert msg.node_name == "gw-home"
    assert msg.node_key == "aabbcc"


def test_companion_disconnected_instantiates():
    msg = CompanionDisconnected()
    assert isinstance(msg, CompanionDisconnected)


def test_companion_connection_error_has_reason():
    msg = CompanionConnectionError(reason="timeout")
    assert msg.reason == "timeout"


def test_channel_message_fields():
    msg = ChannelMessage(
        channel_idx=0,
        channel_name="#public",
        sender="alice",
        text="hello",
        timestamp=12345,
    )
    assert msg.channel_idx == 0
    assert msg.channel_name == "#public"
    assert msg.sender == "alice"
    assert msg.text == "hello"
    assert msg.timestamp == 12345


def test_contact_message_fields():
    msg = ContactMessage(
        pubkey_prefix="aabb",
        sender="bob",
        text="hi there",
        timestamp=99999,
    )
    assert msg.pubkey_prefix == "aabb"
    assert msg.sender == "bob"
    assert msg.text == "hi there"
    assert msg.timestamp == 99999


def test_contacts_updated_stores_list():
    contacts = [{"name": "relay1", "public_key": "aabb"}]
    msg = ContactsUpdated(contacts=contacts)
    assert len(msg.contacts) == 1
    assert msg.contacts[0]["name"] == "relay1"


# ---------------------------------------------------------------------------
# _extract_channel_key_hex
# ---------------------------------------------------------------------------

KEY = bytes.fromhex("52d21b5e68a130279cce6b64c0f8bcd4")


def test_extract_channel_secret_bytes():
    assert _extract_channel_key_hex({"channel_secret": KEY}) == KEY.hex()


def test_extract_legacy_key_field():
    assert _extract_channel_key_hex({"key": KEY}) == KEY.hex()


def test_extract_all_zero_key_skipped():
    assert _extract_channel_key_hex({"channel_secret": bytes(16)}) == ""


def test_extract_missing_field_returns_empty():
    assert _extract_channel_key_hex({"channel_idx": 0, "channel_name": "X"}) == ""


def test_extract_hex_string_field():
    assert _extract_channel_key_hex({"secret": KEY.hex()}) == KEY.hex()
