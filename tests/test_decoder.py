"""Tests for lma.decoder.decode_packet."""

import struct

from meshcore_tools.decoder import decode_packet


# ---------------------------------------------------------------------------
# Packet builders
# ---------------------------------------------------------------------------

def _header(route_type: int, payload_type: int, version: int = 0) -> int:
    return (version << 6) | (payload_type << 2) | route_type


def _flood_ack(payload: bytes = b"\xaa\xbb") -> bytes:
    """Flood + Ack, no hops."""
    header = _header(route_type=0x01, payload_type=0x03)  # Flood + Ack
    path_byte = 0x00  # hash_size=1, 0 hops
    return bytes([header, path_byte]) + payload


def _flood_textmsg(dest: bytes, src: bytes, hops: tuple[bytes, ...] | list[bytes] = ()) -> bytes:
    """Flood + TextMessage with optional relay hops."""
    header = _header(route_type=0x01, payload_type=0x02)  # Flood + TextMessage
    hop_count = len(hops)
    hash_size = len(hops[0]) if hops else 4
    path_byte = ((hash_size - 1) << 6) | hop_count
    path_data = b"".join(hops)
    payload = dest + src + b"\x00\x00" + b"\xff" * 8  # mac + fake ciphertext
    return bytes([header, path_byte]) + path_data + payload


def _advert_packet(pub_key: bytes, lat: float | None = None, lon: float | None = None,
                   name: str | None = None, role: int = 1) -> bytes:
    """Flood + Advert with optional location and name."""
    header = _header(route_type=0x01, payload_type=0x04)  # Flood + Advert
    path_byte = 0x00  # hash_size=1, 0 hops

    timestamp = struct.pack("<I", 0x12345678)
    signature = b"\x00" * 64

    flags = role & 0x0F
    if lat is not None and lon is not None:
        flags |= 0x10  # HasLocation
    if name is not None:
        flags |= 0x80  # HasName

    payload = pub_key[:32] + timestamp + signature + bytes([flags])
    if lat is not None and lon is not None:
        payload += struct.pack("<i", int(lat * 1_000_000))
        payload += struct.pack("<i", int(lon * 1_000_000))
    if name is not None:
        payload += name.encode() + b"\x00"

    return bytes([header, path_byte]) + payload


# ---------------------------------------------------------------------------
# Tests — error paths
# ---------------------------------------------------------------------------

def test_decode_empty():
    result = decode_packet("")
    assert "error" in result


def test_decode_invalid_hex():
    result = decode_packet("zzzz")
    assert result == {"error": "Invalid hex data"}


def test_decode_too_short():
    result = decode_packet("0a")
    assert "error" in result


# ---------------------------------------------------------------------------
# Tests — Flood + Ack
# ---------------------------------------------------------------------------

def test_decode_flood_ack_route_type():
    result = decode_packet(_flood_ack().hex())
    assert result["route_type"] == "Flood"


def test_decode_flood_ack_payload_type():
    result = decode_packet(_flood_ack().hex())
    assert result["payload_type"] == "Ack"


def test_decode_flood_ack_no_hops():
    result = decode_packet(_flood_ack().hex())
    assert result["path"] == []


def test_decode_flood_ack_version():
    result = decode_packet(_flood_ack().hex())
    assert result["payload_version"] == 0


# ---------------------------------------------------------------------------
# Tests — Flood + TextMessage
# ---------------------------------------------------------------------------

def test_decode_textmsg_hashes():
    dest = bytes([0xDE])
    src = bytes([0xCA])
    packet = _flood_textmsg(dest, src)
    result = decode_packet(packet.hex())
    assert result["payload_type"] == "TextMessage"
    assert result["decoded"]["dest_hash"] == "de"
    assert result["decoded"]["src_hash"] == "ca"
    assert result["decoded"]["encrypted"] is True


def test_decode_textmsg_with_hops():
    hop1 = bytes([0xAA, 0xBB, 0xCC, 0xDD])
    hop2 = bytes([0x11, 0x22, 0x33, 0x44])
    dest = bytes([0xDE])
    src = bytes([0xCA])
    packet = _flood_textmsg(dest, src, hops=[hop1, hop2])
    result = decode_packet(packet.hex())
    assert len(result["path"]) == 2
    assert result["path"][0] == "aabbccdd"
    assert result["path"][1] == "11223344"


# ---------------------------------------------------------------------------
# Tests — Flood + Advert
# ---------------------------------------------------------------------------

def test_decode_advert_pubkey():
    pub = bytes(range(32))
    packet = _advert_packet(pub)
    result = decode_packet(packet.hex())
    assert result["payload_type"] == "Advert"
    assert result["decoded"]["public_key"] == pub.hex()


def test_decode_advert_with_location():
    pub = b"\x01" * 32
    packet = _advert_packet(pub, lat=49.5, lon=6.2)
    result = decode_packet(packet.hex())
    dec = result["decoded"]
    assert abs(dec["lat"] - 49.5) < 0.0001
    assert abs(dec["lon"] - 6.2) < 0.0001


def test_decode_advert_without_location():
    pub = b"\x02" * 32
    packet = _advert_packet(pub)
    result = decode_packet(packet.hex())
    assert "lat" not in result["decoded"]
    assert "lon" not in result["decoded"]


def test_decode_advert_with_name():
    pub = b"\x03" * 32
    packet = _advert_packet(pub, name="my-node")
    result = decode_packet(packet.hex())
    assert result["decoded"]["name"] == "my-node"


def test_decode_advert_role():
    pub = b"\x04" * 32
    packet = _advert_packet(pub, role=2)  # Repeater
    result = decode_packet(packet.hex())
    assert result["decoded"]["role"] == "Repeater"


def test_decode_advert_unknown_role():
    pub = b"\x05" * 32
    packet = _advert_packet(pub, role=15)  # unknown role
    result = decode_packet(packet.hex())
    assert result["decoded"]["role"] == "role15"


def test_decode_advert_truncated_location():
    """has_location flag set but payload too short — should get location_error."""
    header = _header(route_type=0x01, payload_type=0x04)
    path_byte = 0x00
    timestamp = struct.pack("<I", 0)
    signature = b"\x00" * 64
    flags = 0x10 | 0x01  # HasLocation + role=ChatNode
    # Payload has flags but only 3 extra bytes (needs 8 for lat+lon)
    payload = b"\x00" * 32 + timestamp + signature + bytes([flags]) + b"\x01\x02\x03"
    packet = bytes([header, path_byte]) + payload
    result = decode_packet(packet.hex())
    assert result["decoded"]["location_error"] == "truncated"


def test_decode_advert_with_feature_flags():
    """HAS_FEATURE1 and HAS_FEATURE2 flags skip 2 bytes each before reading name."""
    header = _header(route_type=0x01, payload_type=0x04)
    path_byte = 0x00
    timestamp = struct.pack("<I", 0)
    signature = b"\x00" * 64
    # HAS_FEATURE1 (bit5) + HAS_FEATURE2 (bit6) + HAS_NAME (bit7)
    flags = 0x20 | 0x40 | 0x80 | 0x01
    feature1 = b"\xAA\xBB"
    feature2 = b"\xCC\xDD"
    name = b"test-node\x00"
    payload = b"\x00" * 32 + timestamp + signature + bytes([flags]) + feature1 + feature2 + name
    packet = bytes([header, path_byte]) + payload
    result = decode_packet(packet.hex())
    assert result["decoded"]["name"] == "test-node"


def test_decode_advert_empty_name():
    """has_name flag set but no bytes remain — name should be empty string."""
    header = _header(route_type=0x01, payload_type=0x04)
    path_byte = 0x00
    timestamp = struct.pack("<I", 0)
    signature = b"\x00" * 64
    flags = 0x80 | 0x01  # HAS_NAME only
    # Payload ends exactly at flag byte — no bytes for name
    payload = b"\x00" * 32 + timestamp + signature + bytes([flags])
    packet = bytes([header, path_byte]) + payload
    result = decode_packet(packet.hex())
    assert result["decoded"]["name"] == ""


def test_decode_advert_non_utf8_name():
    """Name bytes that are not valid UTF-8 should fall back to hex string."""
    header = _header(route_type=0x01, payload_type=0x04)
    path_byte = 0x00
    timestamp = struct.pack("<I", 0)
    signature = b"\x00" * 64
    flags = 0x80 | 0x01  # HAS_NAME
    bad_bytes = b"\x80\x81\x82"  # invalid UTF-8
    payload = b"\x00" * 32 + timestamp + signature + bytes([flags]) + bad_bytes
    packet = bytes([header, path_byte]) + payload
    result = decode_packet(packet.hex())
    assert result["decoded"]["name"] == bad_bytes.hex()


# ---------------------------------------------------------------------------
# Tests — TransportFlood route type
# ---------------------------------------------------------------------------

def _transport_flood_ack(payload: bytes = b"\xaa\xbb") -> bytes:
    """TransportFlood + Ack with transport codes."""
    header = _header(route_type=0x00, payload_type=0x03)  # TransportFlood + Ack
    transport_codes = struct.pack("<HH", 0x1234, 0x5678)
    path_byte = 0x00  # 0 hops
    return bytes([header]) + transport_codes + bytes([path_byte]) + payload


def test_decode_transport_flood_route_type():
    result = decode_packet(_transport_flood_ack().hex())
    assert result["route_type"] == "TransportFlood"


def test_decode_transport_flood_codes_extracted():
    result = decode_packet(_transport_flood_ack().hex())
    assert "transport_codes" in result
    assert result["transport_codes"] == ["1234", "5678"]


def test_decode_transport_too_short_for_codes():
    """Truncated packet after header byte — not enough bytes for transport codes."""
    header = _header(route_type=0x00, payload_type=0x03)
    packet = bytes([header, 0x01])  # only 2 bytes total, needs 5+ for transport
    result = decode_packet(packet.hex())
    assert "error" in result
    assert result["route_type"] == "TransportFlood"


def test_decode_no_path_length_byte():
    """Transport codes parsed, but no byte remains for path_len."""
    header = _header(route_type=0x00, payload_type=0x03)
    transport_codes = struct.pack("<HH", 0x0000, 0x0000)
    # Total = 1 header + 4 transport = 5 bytes, no path byte
    packet = bytes([header]) + transport_codes
    result = decode_packet(packet.hex())
    assert "error" in result
    assert "path" in result["error"].lower() or "path" not in result


def test_decode_too_short_for_path_data():
    """path_len_byte says 3 hops but not enough bytes follow."""
    header = _header(route_type=0x01, payload_type=0x03)  # Flood + Ack
    hop_count = 3
    hash_size = 1
    path_byte = ((hash_size - 1) << 6) | hop_count
    # Only 1 hop byte provided, need 3
    packet = bytes([header, path_byte, 0xAA])
    result = decode_packet(packet.hex())
    assert "error" in result


# ---------------------------------------------------------------------------
# Tests — GroupText (GRP_TXT) and GroupData (GRP_DATA)
# ---------------------------------------------------------------------------

def _grp_txt_packet(payload_type_byte: int, channel_hash: int = 0xAB) -> bytes:
    header = _header(route_type=0x01, payload_type=payload_type_byte)
    path_byte = 0x00  # 0 hops
    # GRP_TXT payload: channel_hash(1) + mac(2) + ciphertext
    payload = bytes([channel_hash, 0x11, 0x22]) + b"\xff" * 16
    return bytes([header, path_byte]) + payload


def test_decode_grp_txt():
    result = decode_packet(_grp_txt_packet(0x05).hex())
    assert result["payload_type"] == "GroupText"
    assert result["decoded"]["channel_hash"] == "ab"
    assert result["decoded"]["cipher_mac"] == "1122"
    assert result["decoded"]["encrypted"] is True


def test_decode_grp_data():
    result = decode_packet(_grp_txt_packet(0x06).hex())
    assert result["payload_type"] == "GroupData"
    assert result["decoded"]["channel_hash"] == "ab"
    assert result["decoded"]["encrypted"] is True


def test_decode_grp_txt_too_short():
    """GRP_TXT payload shorter than 3 bytes."""
    header = _header(route_type=0x01, payload_type=0x05)
    path_byte = 0x00
    payload = bytes([0xAB, 0x11])  # only 2 bytes, need 3
    packet = bytes([header, path_byte]) + payload
    result = decode_packet(packet.hex())
    assert "error" in result["decoded"]


# ---------------------------------------------------------------------------
# Tests — Trace
# ---------------------------------------------------------------------------

def _trace_packet(snr_bytes: bytes = b"") -> bytes:
    header = _header(route_type=0x01, payload_type=0x09)
    path_byte = 0x00
    trace_tag = struct.pack("<I", 0xDEADBEEF)
    auth_code = struct.pack("<I", 0x12345678)
    flags = bytes([0x00])
    payload = trace_tag + auth_code + flags + snr_bytes
    return bytes([header, path_byte]) + payload


def test_decode_trace():
    result = decode_packet(_trace_packet().hex())
    assert result["payload_type"] == "Trace"
    assert result["decoded"]["trace_tag"] == "deadbeef"
    assert result["decoded"]["auth_code"] == "12345678"
    assert result["decoded"]["hop_snrs_db"] == []


def test_decode_trace_with_snrs():
    # SNR bytes: signed int8 / 4 = dB value
    # 0x04 = 4 → 1.0 dB, 0xFC = 252 → signed -4 → -1.0 dB
    snrs = bytes([0x04, 0xFC])
    result = decode_packet(_trace_packet(snrs).hex())
    assert result["decoded"]["hop_snrs_db"] == [1.0, -1.0]


def test_decode_trace_too_short():
    """TRACE payload shorter than 9 bytes."""
    header = _header(route_type=0x01, payload_type=0x09)
    path_byte = 0x00
    packet = bytes([header, path_byte]) + b"\x00" * 8  # needs 9
    result = decode_packet(packet.hex())
    assert "error" in result["decoded"]


# ---------------------------------------------------------------------------
# Tests — Path
# ---------------------------------------------------------------------------

def _path_packet(src: bytes, dst: bytes | None = None, extra: bytes = b"") -> bytes:
    header = _header(route_type=0x01, payload_type=0x08)
    hash_size = len(src)
    path_byte = ((hash_size - 1) << 6) | 0  # 0 hops
    payload = src + (dst or b"") + extra
    return bytes([header, path_byte]) + payload


def test_decode_path_src_and_dst():
    src = bytes([0x11, 0x22, 0x33, 0x44])
    dst = bytes([0x55, 0x66, 0x77, 0x88])
    result = decode_packet(_path_packet(src, dst).hex())
    assert result["payload_type"] == "Path"
    assert result["decoded"]["src_hash"] == "11223344"
    assert result["decoded"]["dst_hash"] == "55667788"


def test_decode_path_src_only():
    src = bytes([0xAA, 0xBB, 0xCC, 0xDD])
    result = decode_packet(_path_packet(src).hex())
    assert result["decoded"]["src_hash"] == "aabbccdd"
    assert "dst_hash" not in result["decoded"]


def test_decode_path_with_extra_hops():
    src = bytes([0x01, 0x02, 0x03, 0x04])
    dst = bytes([0x05, 0x06, 0x07, 0x08])
    extra = bytes([0x09, 0x0A, 0x0B, 0x0C])
    result = decode_packet(_path_packet(src, dst, extra).hex())
    assert result["decoded"]["extra_hops"] == ["090a0b0c"]


def test_decode_path_too_short():
    """PATH payload has fewer bytes than hash_size."""
    header = _header(route_type=0x01, payload_type=0x08)
    # hash_size=4 but payload is empty
    path_byte = ((4 - 1) << 6) | 0
    packet = bytes([header, path_byte])
    result = decode_packet(packet.hex())
    assert "error" in result["decoded"]


# ---------------------------------------------------------------------------
# Tests — Unknown / other payload types
# ---------------------------------------------------------------------------

def test_decode_unknown_payload_type():
    """ACK (0x0B = Control) → else branch → empty decoded dict."""
    header = _header(route_type=0x01, payload_type=0x0B)  # Control
    path_byte = 0x00
    packet = bytes([header, path_byte]) + b"\x01\x02\x03"
    result = decode_packet(packet.hex())
    assert result["payload_type"] == "Control"
    assert result["decoded"] == {}
