"""Tests for companion Textual message classes."""

from meshcore_tools.companion import (
    ChannelMessage,
    CompanionConnected,
    CompanionConnectionError,
    CompanionDisconnected,
    ContactMessage,
    ContactsUpdated,
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
