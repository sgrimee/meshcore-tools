"""MQTT packet provider — subscribes to an MQTT broker for raw LoRa frames."""

from __future__ import annotations

import hashlib
import json
import queue
import threading
from typing import Any


class MqttPacketProvider:
    """PacketProvider that subscribes to an MQTT broker for raw LoRa frames.

    Designed for the MeshCore observer topic structure:
        meshcore/{IATA}/{observer_pubkey}/packets

    A wildcard subscription (e.g. ``meshcore/LUX/+/packets``) receives reports
    from every observer in the region.  Each report is one *observation* of a
    logical packet; the canonical packet hash in the payload is used as ``id``
    so that duplicate sightings from different observers are naturally dropped
    by the monitor's ``_seen_ids`` dedup.

    Payload formats accepted:
    - JSON object (preferred) — fields described in ``_parse_payload``
    - Plain hex string — treated as raw LoRa frame with no metadata

    Each returned packet dict has the shape expected by MonitorTab._ingest_packets:
        {
            "id":        str,        # packet hash or sha256 fallback
            "regions":   [str],
            "raw_data":  str,        # hex-encoded LoRa frame
            "origin_id": str,        # observer pubkey (from topic)
            "origin":    str,        # observer name (from payload, may be "")
            "snr":       float|None,
            "rssi":      int|None,
            "heard_at":  str,        # ISO datetime or ""
        }
    """

    def __init__(
        self,
        broker: str,
        port: int = 1883,
        topic: str = "meshcore/raw",
        username: str | None = None,
        password: str | None = None,
        region: str = "LUX",
    ) -> None:
        self._broker = broker
        self._port = port
        self._topic = topic
        self._username = username
        self._password = password
        self._region = region
        self._queue: queue.Queue[dict] = queue.Queue()
        self._connected = False
        self._lock = threading.Lock()
        self._client: Any = None

    # ------------------------------------------------------------------
    # PacketProvider protocol
    # ------------------------------------------------------------------

    def fetch_packets(self, region: str, limit: int = 50) -> list[dict]:
        """Drain the internal buffer and return accumulated packets."""
        self._ensure_connected()
        packets: list[dict] = []
        try:
            while len(packets) < limit:
                packets.append(self._queue.get_nowait())
        except queue.Empty:
            pass
        return packets

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        with self._lock:
            if self._connected:
                return
            self._connect()

    def _connect(self) -> None:
        """Create and start the paho MQTT client (called while holding _lock)."""
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if self._username is not None:
            client.username_pw_set(self._username, self._password)

        client.on_message = self._on_message

        client.connect(self._broker, self._port, keepalive=60)
        client.subscribe(self._topic)

        # loop_forever() in a daemon thread is more reliable than loop_start()
        # across paho 2.x versions.
        t = threading.Thread(target=client.loop_forever, daemon=True)
        t.start()

        self._client = client
        self._connected = True

    def _on_message(self, client: object, userdata: object, message: object) -> None:
        """Paho callback — normalise and enqueue the incoming packet."""
        try:
            topic: str = message.topic  # type: ignore[union-attr]
            payload_bytes: bytes = message.payload  # type: ignore[union-attr]
            pkt = self._parse_payload(payload_bytes, topic)
            if pkt is not None:
                self._queue.put(pkt)
        except Exception:
            pass

    def _parse_payload(self, payload_bytes: bytes, topic: str) -> dict | None:
        """Parse an MQTT message into a packet dict, or return None to discard."""
        # Extract observer pubkey from topic path: meshcore/{IATA}/{pubkey}/packets
        parts = topic.split("/")
        origin_id = parts[2] if len(parts) >= 4 else ""

        text = payload_bytes.decode(errors="replace").strip()

        # --- JSON payload (preferred) ---
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                return None

            raw_hex = _str_field(data, "raw_data", "data", "raw")
            if not raw_hex:
                return None
            raw_hex = raw_hex.lower()

            # Canonical packet hash → dedup key; fallback to sha256 of bytes
            pkt_hash = _str_field(data, "hash", "packet_hash")
            packet_id = pkt_hash.lower() if pkt_hash else hashlib.sha256(raw_hex.encode()).hexdigest()[:16]

            # Field names vary by broker (case-sensitive JSON keys)
            snr_raw = data.get("snr") if data.get("snr") is not None else data.get("SNR")
            rssi_raw = data.get("rssi") if data.get("rssi") is not None else data.get("RSSI")

            return {
                "id": packet_id,
                "regions": [self._region],
                "raw_data": raw_hex,
                "origin_id": origin_id,
                "origin": data.get("origin") or "",
                "snr": float(snr_raw) if snr_raw is not None else None,
                "rssi": int(rssi_raw) if rssi_raw is not None else None,
                "heard_at": data.get("heard_at") or data.get("timestamp") or "",
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        # --- Plain hex string fallback ---
        cleaned = text.replace(" ", "")
        if cleaned and all(c in "0123456789abcdefABCDEF" for c in cleaned):
            raw_hex = cleaned.lower()
            return {
                "id": hashlib.sha256(raw_hex.encode()).hexdigest()[:16],
                "regions": [self._region],
                "raw_data": raw_hex,
                "origin_id": origin_id,
                "origin": "",
                "snr": None,
                "rssi": None,
                "heard_at": "",
            }

        return None

    def disconnect(self) -> None:
        """Disconnect from the broker (the daemon loop thread will exit on its own)."""
        with self._lock:
            if self._client is not None:
                self._client.disconnect()
            self._connected = False
            self._client = None


def _str_field(d: dict, *keys: str) -> str:
    """Return the first non-empty string value found among the given keys."""
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v:
            return v
    return ""
