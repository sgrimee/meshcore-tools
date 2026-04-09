"""Tests for MqttPacketProvider — no live broker required."""

from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock, patch

from meshcore_tools.providers.mqtt_provider import MqttPacketProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOPIC_LUX = "meshcore/LUX/B19BFD1234567890/packets"
TOPIC_SCN = "meshcore/SCN/AABBCCDD12345678/packets"


def _make_provider(
    broker: str = "localhost",
    region: str = "LUX",
    username: str | None = None,
    password: str | None = None,
    port: int = 1883,
    topic: str = "meshcore/LUX/+/packets",
) -> MqttPacketProvider:
    return MqttPacketProvider(
        broker=broker,
        region=region,
        username=username,
        password=password,
        port=port,
        topic=topic,
    )


def _push(provider: MqttPacketProvider, payload: bytes, topic: str = TOPIC_LUX) -> None:
    """Simulate an MQTT message arriving."""
    msg = MagicMock()
    msg.payload = payload
    msg.topic = topic
    provider._on_message(None, None, msg)


def _json(raw_hex: str = "deadbeef", **extra) -> bytes:
    return json.dumps({"raw_data": raw_hex, **extra}).encode()


# ---------------------------------------------------------------------------
# _parse_payload — JSON payloads
# ---------------------------------------------------------------------------

class TestParsePayloadJson:
    def test_raw_data_field(self):
        p = _make_provider()
        pkt = p._parse_payload(_json("deadbeef"), TOPIC_LUX)
        assert pkt is not None
        assert pkt["raw_data"] == "deadbeef"

    def test_data_field_fallback(self):
        p = _make_provider()
        payload = json.dumps({"data": "cafebabe"}).encode()
        pkt = p._parse_payload(payload, TOPIC_LUX)
        assert pkt is not None
        assert pkt["raw_data"] == "cafebabe"

    def test_raw_field_accepted(self):
        """Broker uses 'raw' as the hex bytes field name."""
        p = _make_provider()
        payload = json.dumps({"raw": "cafebabe"}).encode()
        pkt = p._parse_payload(payload, TOPIC_LUX)
        assert pkt is not None
        assert pkt["raw_data"] == "cafebabe"

    def test_hash_used_as_id(self):
        p = _make_provider()
        pkt = p._parse_payload(_json("aabb", hash="abc123def456"), TOPIC_LUX)
        assert pkt is not None
        assert pkt["id"] == "abc123def456"

    def test_packet_hash_field_also_accepted(self):
        p = _make_provider()
        payload = json.dumps({"raw_data": "aabb", "packet_hash": "xyz789"}).encode()
        pkt = p._parse_payload(payload, TOPIC_LUX)
        assert pkt is not None
        assert pkt["id"] == "xyz789"

    def test_sha256_fallback_when_no_hash(self):
        p = _make_provider()
        raw = "aabbccdd"
        pkt = p._parse_payload(_json(raw), TOPIC_LUX)
        assert pkt is not None
        expected = hashlib.sha256(raw.encode()).hexdigest()[:16]
        assert pkt["id"] == expected

    def test_snr_rssi_heard_at_passed_through(self):
        p = _make_provider()
        payload = _json("aabb", snr=7.5, rssi=-95, heard_at="2026-04-08T12:00:00Z")
        pkt = p._parse_payload(payload, TOPIC_LUX)
        assert pkt is not None
        assert pkt["snr"] == 7.5
        assert pkt["rssi"] == -95
        assert pkt["heard_at"] == "2026-04-08T12:00:00Z"

    def test_uppercase_snr_rssi(self):
        """Broker sends SNR and RSSI with uppercase keys."""
        p = _make_provider()
        payload = json.dumps({"raw": "aabb", "SNR": 12.25, "RSSI": -50}).encode()
        pkt = p._parse_payload(payload, TOPIC_LUX)
        assert pkt is not None
        assert pkt["snr"] == 12.25
        assert pkt["rssi"] == -50

    def test_timestamp_fallback_for_heard_at(self):
        p = _make_provider()
        payload = _json("aabb", timestamp="2026-04-08T10:00:00Z")
        pkt = p._parse_payload(payload, TOPIC_LUX)
        assert pkt is not None
        assert pkt["heard_at"] == "2026-04-08T10:00:00Z"

    def test_origin_name_from_payload(self):
        p = _make_provider()
        pkt = p._parse_payload(_json("aabb", origin="GW-Charly"), TOPIC_LUX)
        assert pkt is not None
        assert pkt["origin"] == "GW-Charly"

    def test_missing_raw_data_returns_none(self):
        p = _make_provider()
        payload = json.dumps({"snr": 5.0, "rssi": -80}).encode()
        assert p._parse_payload(payload, TOPIC_LUX) is None

    def test_missing_snr_rssi_are_none(self):
        p = _make_provider()
        pkt = p._parse_payload(_json("aabb"), TOPIC_LUX)
        assert pkt is not None
        assert pkt["snr"] is None
        assert pkt["rssi"] is None

    def test_region_injected(self):
        p = _make_provider(region="SCN")
        pkt = p._parse_payload(_json("aabb"), TOPIC_SCN)
        assert pkt is not None
        assert pkt["regions"] == ["SCN"]

    def test_hex_normalised_to_lowercase(self):
        p = _make_provider()
        pkt = p._parse_payload(_json("DEADBEEF"), TOPIC_LUX)
        assert pkt is not None
        assert pkt["raw_data"] == "deadbeef"

    def test_hash_normalised_to_lowercase(self):
        p = _make_provider()
        pkt = p._parse_payload(_json("aabb", hash="ABCDEF123456"), TOPIC_LUX)
        assert pkt is not None
        assert pkt["id"] == "abcdef123456"


# ---------------------------------------------------------------------------
# _parse_payload — observer ID from topic
# ---------------------------------------------------------------------------

class TestParsePayloadTopic:
    def test_observer_id_from_topic(self):
        p = _make_provider()
        pkt = p._parse_payload(_json("aabb"), "meshcore/LUX/B19BFD1234567890/packets")
        assert pkt is not None
        assert pkt["origin_id"] == "B19BFD1234567890"

    def test_different_observer_different_origin_id(self):
        p = _make_provider()
        pkt = p._parse_payload(_json("aabb"), "meshcore/SCN/AABBCC99/packets")
        assert pkt is not None
        assert pkt["origin_id"] == "AABBCC99"

    def test_short_topic_origin_id_empty(self):
        p = _make_provider()
        pkt = p._parse_payload(_json("aabb"), "meshcore/raw")
        assert pkt is not None
        assert pkt["origin_id"] == ""


# ---------------------------------------------------------------------------
# _parse_payload — plain hex fallback
# ---------------------------------------------------------------------------

class TestParsePayloadPlainHex:
    def test_plain_hex_accepted(self):
        p = _make_provider()
        pkt = p._parse_payload(b"deadbeef", TOPIC_LUX)
        assert pkt is not None
        assert pkt["raw_data"] == "deadbeef"

    def test_plain_hex_no_metadata(self):
        p = _make_provider()
        pkt = p._parse_payload(b"aabb", TOPIC_LUX)
        assert pkt is not None
        assert pkt["snr"] is None
        assert pkt["rssi"] is None
        assert pkt["heard_at"] == ""

    def test_plain_hex_observer_from_topic(self):
        p = _make_provider()
        pkt = p._parse_payload(b"aabb", "meshcore/LUX/OBSERVER01/packets")
        assert pkt is not None
        assert pkt["origin_id"] == "OBSERVER01"

    def test_invalid_payload_returns_none(self):
        p = _make_provider()
        assert p._parse_payload(b"not valid hex!", TOPIC_LUX) is None

    def test_empty_payload_returns_none(self):
        p = _make_provider()
        assert p._parse_payload(b"", TOPIC_LUX) is None


# ---------------------------------------------------------------------------
# _on_message enqueue behaviour
# ---------------------------------------------------------------------------

class TestOnMessage:
    def test_valid_packet_enqueued(self):
        p = _make_provider()
        _push(p, _json("aabbcc"))
        assert p._queue.qsize() == 1

    def test_invalid_payload_not_enqueued(self):
        p = _make_provider()
        _push(p, b"not valid")
        assert p._queue.qsize() == 0

    def test_same_hash_from_two_observers_produces_same_id(self):
        """Same logical packet seen by two observers should have the same id."""
        p = _make_provider()
        payload = _json("aabb", hash="deadbeef12345678")
        _push(p, payload, topic="meshcore/LUX/OBSERVER_A/packets")
        _push(p, payload, topic="meshcore/LUX/OBSERVER_B/packets")
        id1 = p._queue.get_nowait()["id"]
        id2 = p._queue.get_nowait()["id"]
        assert id1 == id2  # same hash → monitor's _seen_ids will dedup the second

    def test_different_raw_data_different_id(self):
        p = _make_provider()
        _push(p, _json("aabb"))
        _push(p, _json("ccdd"))
        id1 = p._queue.get_nowait()["id"]
        id2 = p._queue.get_nowait()["id"]
        assert id1 != id2


# ---------------------------------------------------------------------------
# fetch_packets
# ---------------------------------------------------------------------------

class TestFetchPackets:
    def _patched_provider(
        self,
        region: str = "LUX",
        username: str | None = None,
        password: str | None = None,
    ) -> MqttPacketProvider:
        """Provider with a mocked paho client so _connect() doesn't try a real broker."""
        provider = _make_provider(region=region, username=username, password=password)
        mock_client = MagicMock()
        with patch("paho.mqtt.client.Client", return_value=mock_client):
            provider._connect()
        return provider

    def test_drains_all_queued_packets(self):
        provider = self._patched_provider()
        _push(provider, _json("aabb"))
        _push(provider, _json("ccdd"))
        packets = provider.fetch_packets("LUX", limit=50)
        assert len(packets) == 2
        assert provider._queue.qsize() == 0

    def test_respects_limit(self):
        provider = self._patched_provider()
        for i in range(10):
            _push(provider, _json(f"aa{i:02x}"))
        packets = provider.fetch_packets("LUX", limit=3)
        assert len(packets) == 3
        assert provider._queue.qsize() == 7

    def test_returns_empty_when_no_packets(self):
        provider = self._patched_provider()
        assert provider.fetch_packets("LUX") == []

    def test_connects_once(self):
        provider = _make_provider()
        mock_client = MagicMock()
        with patch("paho.mqtt.client.Client", return_value=mock_client) as MockClient:
            provider.fetch_packets("LUX")
            provider.fetch_packets("LUX")
        MockClient.assert_called_once()

    def test_sets_credentials_when_provided(self):
        provider = _make_provider(username="alice", password="secret")
        mock_client = MagicMock()
        with patch("paho.mqtt.client.Client", return_value=mock_client):
            provider._connect()
        mock_client.username_pw_set.assert_called_once_with("alice", "secret")

    def test_no_credentials_when_not_provided(self):
        provider = _make_provider()
        mock_client = MagicMock()
        with patch("paho.mqtt.client.Client", return_value=mock_client):
            provider._connect()
        mock_client.username_pw_set.assert_not_called()
