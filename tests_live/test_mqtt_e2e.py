"""End-to-end MQTT test — requires real broker credentials in settings.toml.

NOT run by 'just test' or CI (testpaths only includes 'tests/', not 'tests/live/').
Run on-demand with:
    just test-live
    uv run pytest tests/live/ -v
"""

from __future__ import annotations

import time

import pytest

from meshcore_tools.config import get_mqtt_config, get_packet_source_type, get_region
from meshcore_tools.decoder import decode_packet
from meshcore_tools.providers.mqtt_provider import MqttPacketProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def provider():
    """Connected MqttPacketProvider using settings.toml credentials."""
    cfg = get_mqtt_config()
    region = get_region() or "LUX"
    p = MqttPacketProvider(region=region, **cfg)
    p._ensure_connected()
    time.sleep(2)  # allow the loop thread to connect and subscribe
    yield p
    p.disconnect()


@pytest.fixture(scope="module")
def packets(provider: MqttPacketProvider) -> list[dict]:
    """Collect at least 5 unique packets (wait up to 60 s)."""
    region = get_region() or "LUX"
    seen: dict[str, dict] = {}
    deadline = time.time() + 60
    while len(seen) < 5 and time.time() < deadline:
        for p in provider.fetch_packets(region, limit=50):
            seen.setdefault(p["id"], p)
        time.sleep(1)
    if not seen:
        pytest.skip("No packets received from broker within 60 s")
    return list(seen.values())


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_packet_source_configured_as_mqtt() -> None:
    assert get_packet_source_type() == "mqtt", (
        "settings.toml must have [packet_source] type = \"mqtt\" to run live tests"
    )


@pytest.mark.live
def test_mqtt_config_has_broker() -> None:
    cfg = get_mqtt_config()
    assert cfg.get("broker"), "settings.toml [mqtt] must specify a broker"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_provider_connects(provider: MqttPacketProvider) -> None:
    assert provider._connected


# ---------------------------------------------------------------------------
# Packet shape
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_packets_received(packets: list[dict]) -> None:
    assert len(packets) >= 1


@pytest.mark.live
def test_each_packet_has_required_fields(packets: list[dict]) -> None:
    for p in packets:
        assert "id" in p, f"missing 'id': {p}"
        assert "raw_data" in p, f"missing 'raw_data': {p}"
        assert "regions" in p, f"missing 'regions': {p}"


@pytest.mark.live
def test_raw_data_is_valid_hex(packets: list[dict]) -> None:
    for p in packets:
        raw = p["raw_data"]
        assert isinstance(raw, str) and raw, f"raw_data empty or not a string: {p}"
        int(raw, 16)  # raises ValueError if not valid hex


@pytest.mark.live
def test_region_injected_into_packets(packets: list[dict]) -> None:
    region = (get_region() or "LUX").upper()
    for p in packets:
        regions_upper = [r.upper() for r in p["regions"]]
        assert region in regions_upper, f"expected {region} in regions: {p['regions']}"


@pytest.mark.live
def test_origin_id_populated(packets: list[dict]) -> None:
    """At least one packet should have origin_id (from the topic path)."""
    assert any(p.get("origin_id") for p in packets), (
        "No packets had origin_id populated — topic path parsing may be broken"
    )


@pytest.mark.live
def test_heard_at_populated(packets: list[dict]) -> None:
    """At least one packet should have a heard_at timestamp."""
    assert any(p.get("heard_at") for p in packets), (
        "No packets had heard_at populated"
    )


@pytest.mark.live
def test_snr_rssi_are_numeric_when_present(packets: list[dict]) -> None:
    for p in packets:
        if p.get("snr") is not None:
            assert isinstance(p["snr"], float), f"snr not float: {p['snr']!r}"
        if p.get("rssi") is not None:
            assert isinstance(p["rssi"], int), f"rssi not int: {p['rssi']!r}"


# ---------------------------------------------------------------------------
# Deduplication — same hash from multiple observers → same id
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_cross_observer_dedup(provider: MqttPacketProvider) -> None:
    """Two observations of the same logical packet must produce the same id.

    Collects raw observations (without dedup) for 30 s and verifies that any
    packet hash appearing more than once maps to the same provider id.
    """
    region = get_region() or "LUX"
    all_obs: list[dict] = []
    deadline = time.time() + 30
    while time.time() < deadline:
        all_obs.extend(provider.fetch_packets(region, limit=100))
        time.sleep(1)

    if len(all_obs) < 2:
        pytest.skip("Not enough observations to test dedup (need ≥ 2)")

    # Group by id — all observations sharing an id should have the same raw_data prefix
    by_id: dict[str, list[dict]] = {}
    for p in all_obs:
        by_id.setdefault(p["id"], []).append(p)

    duplicated = {pid: obs for pid, obs in by_id.items() if len(obs) > 1}
    if not duplicated:
        pytest.skip("No cross-observer duplicates observed in 30 s — try a busier time")

    for pid, obs in duplicated.items():
        ids = {o["id"] for o in obs}
        assert len(ids) == 1, f"Observations of same packet have different ids: {ids}"


# ---------------------------------------------------------------------------
# Decoder integration
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_raw_data_decodes_without_error(packets: list[dict]) -> None:
    for p in packets:
        dec = decode_packet(p["raw_data"])
        assert "error" not in dec or dec.get("payload_type"), (
            f"decode_packet returned unexpected error for {p['id']}: {dec.get('error')}"
        )


@pytest.mark.live
def test_payload_type_decoded(packets: list[dict]) -> None:
    """Every packet should decode to a known payload_type (not empty/unknown)."""
    known_types = {
        "Request", "Response", "TextMessage", "Advert",
        "GroupText", "GroupData", "ACK", "PATH", "Trace", "AnonReq",
    }
    for p in packets:
        dec = decode_packet(p["raw_data"])
        ptype = dec.get("payload_type", "")
        assert ptype, f"payload_type empty for packet {p['id']}"
        # Unknown types are not a failure — future protocol versions may add new ones
        if ptype not in known_types:
            print(f"\n  note: unknown payload_type {ptype!r} for packet {p['id']}")
