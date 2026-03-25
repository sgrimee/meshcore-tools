"""MeshCore raw packet decoder.

Wire format (non-transport):
  Byte 0:   header  — bits 0-1 route_type, bits 2-5 payload_type, bits 6-7 version
  Byte 1:   path_len — bits 7-6 (hash_size-1), bits 5-0 (hop count)
  Bytes 2+: hop data (count × hash_size bytes)
  Rest:     payload

Transport packets (route_type 0x00/0x03) have 4 extra transport-code bytes
before path_len.

Sources:
  github.com/meshcore-dev/MeshCore  — Packet.h / Dispatcher.cpp
  github.com/michaelhart/meshcore-decoder — advert.ts / text-message.ts etc.
"""

from __future__ import annotations

import struct
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROUTE_TRANSPORT_FLOOD = 0x00
ROUTE_FLOOD = 0x01
ROUTE_DIRECT = 0x02
ROUTE_TRANSPORT_DIRECT = 0x03

ROUTE_NAMES = {
    ROUTE_TRANSPORT_FLOOD: "TransportFlood",
    ROUTE_FLOOD: "Flood",
    ROUTE_DIRECT: "Direct",
    ROUTE_TRANSPORT_DIRECT: "TransportDirect",
}

PAYLOAD_REQUEST = 0x00
PAYLOAD_RESPONSE = 0x01
PAYLOAD_TEXT_MSG = 0x02
PAYLOAD_ACK = 0x03
PAYLOAD_ADVERT = 0x04
PAYLOAD_GRP_TXT = 0x05
PAYLOAD_GRP_DATA = 0x06
PAYLOAD_ANON_REQ = 0x07
PAYLOAD_PATH = 0x08
PAYLOAD_TRACE = 0x09
PAYLOAD_MULTIPART = 0x0A
PAYLOAD_CONTROL = 0x0B
PAYLOAD_RAW_CUSTOM = 0x0F

PAYLOAD_NAMES = {
    PAYLOAD_REQUEST: "Request",
    PAYLOAD_RESPONSE: "Response",
    PAYLOAD_TEXT_MSG: "TextMessage",
    PAYLOAD_ACK: "Ack",
    PAYLOAD_ADVERT: "Advert",
    PAYLOAD_GRP_TXT: "GroupText",
    PAYLOAD_GRP_DATA: "GroupData",
    PAYLOAD_ANON_REQ: "AnonRequest",
    PAYLOAD_PATH: "Path",
    PAYLOAD_TRACE: "Trace",
    PAYLOAD_MULTIPART: "Multipart",
    PAYLOAD_CONTROL: "Control",
    PAYLOAD_RAW_CUSTOM: "RawCustom",
}

DEVICE_ROLES = {0: "Unknown", 1: "ChatNode", 2: "Repeater", 3: "RoomServer", 4: "Sensor"}

# ADVERT flags byte (offset 100)
_ADVERT_HAS_LOCATION = 0x10  # bit 4
_ADVERT_HAS_FEATURE1 = 0x20  # bit 5  (2-byte optional field, skip)
_ADVERT_HAS_FEATURE2 = 0x40  # bit 6  (2-byte optional field, skip)
_ADVERT_HAS_NAME = 0x80      # bit 7
_ADVERT_ROLE_MASK = 0x0F     # bits 0-3


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def decode_packet(raw_data: str) -> dict[str, Any]:
    """Decode a raw MeshCore packet from hex string.

    Returns a dict with at minimum:
      route_type, payload_type, payload_version, path (list[str]),
      path_hop_size (int), payload_hex (str), payload_bytes (int).
    On success also includes 'decoded' dict with type-specific fields.
    On any error includes an 'error' key (other fields may still be present).
    """
    try:
        raw = bytes.fromhex(raw_data)
    except Exception:
        return {"error": "Invalid hex data"}

    result: dict[str, Any] = {}

    if len(raw) < 2:
        return {"error": "Packet too short"}

    try:
        offset = 0

        # --- Header ---
        header = raw[0]
        route_type = header & 0x03
        payload_type = (header >> 2) & 0x0F
        payload_version = (header >> 6) & 0x03
        offset = 1

        result["route_type"] = ROUTE_NAMES.get(route_type, f"0x{route_type:02x}")
        result["payload_type"] = PAYLOAD_NAMES.get(payload_type, f"0x{payload_type:02x}")
        result["payload_version"] = payload_version

        # --- Transport codes (4 bytes, only for transport route types) ---
        if route_type in (ROUTE_TRANSPORT_FLOOD, ROUTE_TRANSPORT_DIRECT):
            if len(raw) < offset + 4:
                return result | {"error": "Too short for transport codes"}
            c1 = struct.unpack_from("<H", raw, offset)[0]
            c2 = struct.unpack_from("<H", raw, offset + 2)[0]
            result["transport_codes"] = [f"{c1:04x}", f"{c2:04x}"]
            offset += 4

        # --- Path ---
        if len(raw) <= offset:
            return result | {"error": "No path length byte"}

        path_len_byte = raw[offset]
        hash_size = (path_len_byte >> 6) + 1
        hop_count = path_len_byte & 0x3F
        offset += 1

        total_path_bytes = hop_count * hash_size
        if len(raw) < offset + total_path_bytes:
            return result | {"error": "Too short for path data"}

        result["path"] = [
            raw[offset + i * hash_size: offset + (i + 1) * hash_size].hex()
            for i in range(hop_count)
        ]
        result["path_hop_size"] = hash_size
        offset += total_path_bytes

        # --- Payload ---
        payload = raw[offset:]
        result["payload_hex"] = payload.hex()
        result["payload_bytes"] = len(payload)

        if payload_type == PAYLOAD_ADVERT:
            result["decoded"] = _decode_advert(payload)
        elif payload_type in (PAYLOAD_REQUEST, PAYLOAD_RESPONSE,
                               PAYLOAD_TEXT_MSG, PAYLOAD_ANON_REQ):
            result["decoded"] = _decode_with_hashes(payload)
        elif payload_type == PAYLOAD_GRP_TXT:
            result["decoded"] = _decode_group_text(payload)
        elif payload_type == PAYLOAD_GRP_DATA:
            result["decoded"] = _decode_group_text(payload)  # same prefix layout
        elif payload_type == PAYLOAD_TRACE:
            result["decoded"] = _decode_trace(payload)
        elif payload_type == PAYLOAD_ACK:
            result["decoded"] = _decode_ack(payload)
        elif payload_type == PAYLOAD_PATH:
            result["decoded"] = _decode_path(payload, hash_size)
        else:
            result["decoded"] = {}

    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# Per-type payload decoders
# ---------------------------------------------------------------------------

def _decode_advert(payload: bytes) -> dict[str, Any]:
    """ADVERT (0x04) — fully unencrypted broadcast.

    Layout (minimum 101 bytes):
      [0-31]   public_key   Ed25519 pubkey (32 bytes)
      [32-35]  timestamp    uint32 LE
      [36-99]  signature    Ed25519 signature (64 bytes)
      [100]    flags        bits 0-3=role, bit4=HasLocation, bit7=HasName
      [101+]   optional location: lat int32 LE + lon int32 LE (÷1e6 → degrees)
      [...]    optional name: UTF-8 null-terminated string
    """
    if len(payload) < 101:
        return {"error": f"Too short for Advert ({len(payload)} < 101 bytes)"}

    pub_key = payload[0:32].hex()
    timestamp = struct.unpack_from("<I", payload, 32)[0]
    signature = payload[36:100].hex()
    flags = payload[100]

    role_id = flags & _ADVERT_ROLE_MASK
    has_location = bool(flags & _ADVERT_HAS_LOCATION)
    has_name = bool(flags & _ADVERT_HAS_NAME)

    result: dict[str, Any] = {
        "public_key": pub_key,
        "timestamp": timestamp,
        "signature": signature,
        "flags": f"0x{flags:02x}",
        "role": DEVICE_ROLES.get(role_id, f"role{role_id}"),
    }

    pos = 101
    if has_location:
        if len(payload) >= pos + 8:
            lat_int = struct.unpack_from("<i", payload, pos)[0]
            lon_int = struct.unpack_from("<i", payload, pos + 4)[0]
            result["lat"] = round(lat_int / 1_000_000, 6)
            result["lon"] = round(lon_int / 1_000_000, 6)
            pos += 8
        else:
            result["location_error"] = "truncated"

    if flags & _ADVERT_HAS_FEATURE1:
        pos += 2
    if flags & _ADVERT_HAS_FEATURE2:
        pos += 2

    if has_name:
        if len(payload) > pos:
            try:
                result["name"] = payload[pos:].decode("utf-8").rstrip("\x00")
            except Exception:
                result["name"] = payload[pos:].hex()
        else:
            result["name"] = ""

    return result


def _decode_with_hashes(payload: bytes) -> dict[str, Any]:
    """REQUEST(0x00) / RESPONSE(0x01) / TEXT_MSG(0x02) / ANON_REQ(0x07).

    Plaintext prefix:
      [0]   dest_hash   first byte of destination pubkey
      [1]   src_hash    first byte of source pubkey
      [2-3] cipher_mac  2-byte MAC
      [4+]  ciphertext  encrypted (cannot decode without key)
    """
    if len(payload) < 4:
        return {"error": f"Too short ({len(payload)} < 4 bytes)"}

    return {
        "dest_hash": payload[0:1].hex(),
        "src_hash": payload[1:2].hex(),
        "cipher_mac": payload[2:4].hex(),
        "ciphertext_len": len(payload) - 4,
        "encrypted": True,
    }


def _decode_group_text(payload: bytes) -> dict[str, Any]:
    """GRP_TXT(0x05) / GRP_DATA(0x06).

    Plaintext prefix:
      [0]   channel_hash  first byte of SHA256(channel_secret)
      [1-2] cipher_mac    2-byte MAC
      [3+]  ciphertext    encrypted
    """
    if len(payload) < 3:
        return {"error": f"Too short ({len(payload)} < 3 bytes)"}

    return {
        "channel_hash": payload[0:1].hex(),
        "cipher_mac": payload[1:3].hex(),
        "ciphertext_len": len(payload) - 3,
        "encrypted": True,
    }


def _decode_trace(payload: bytes) -> dict[str, Any]:
    """TRACE(0x09).

    Layout (minimum 9 bytes):
      [0-3]  trace_tag   uint32 LE
      [4-7]  auth_code   uint32 LE
      [8]    flags       uint8
      [9+]   path_snrs   signed int8 per hop, value/4 = SNR in dB
    """
    if len(payload) < 9:
        return {"error": f"Too short for Trace ({len(payload)} < 9 bytes)"}

    trace_tag = struct.unpack_from("<I", payload, 0)[0]
    auth_code = struct.unpack_from("<I", payload, 4)[0]
    flags = payload[8]

    snrs = []
    for b in payload[9:]:
        signed = b if b < 128 else b - 256
        snrs.append(round(signed / 4.0, 2))

    return {
        "trace_tag": f"{trace_tag:08x}",
        "auth_code": f"{auth_code:08x}",
        "flags": f"0x{flags:02x}",
        "hop_snrs_db": snrs,
    }


def _decode_ack(payload: bytes) -> dict[str, Any]:
    """ACK(0x03) — minimal fixed payload."""
    return {"raw": payload.hex(), "length": len(payload)}


def _decode_path(payload: bytes, hash_size: int) -> dict[str, Any]:
    """PATH(0x08) — route discovery probe/reply.

    Layout:
      [0..hash_size-1]              src_hash   sender's node hash
      [hash_size..2*hash_size-1]    dst_hash   destination node hash (if present)
      [2*hash_size+]                extra      additional hop hashes (if any)
    """
    if len(payload) < hash_size:
        return {"error": f"Too short for Path ({len(payload)} < {hash_size} bytes)"}

    result: dict[str, Any] = {
        "src_hash": payload[0:hash_size].hex(),
    }
    if len(payload) >= 2 * hash_size:
        result["dst_hash"] = payload[hash_size:2 * hash_size].hex()
    extra = payload[2 * hash_size:]
    if extra:
        result["extra_hops"] = [
            extra[i * hash_size:(i + 1) * hash_size].hex()
            for i in range(len(extra) // hash_size)
        ]
    return result
