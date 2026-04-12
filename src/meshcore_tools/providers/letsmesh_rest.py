"""letsmesh.net REST provider — implements NodeProvider and PacketProvider."""

import json
import urllib.request
from typing import Any

DEFAULT_REGION = "LUX"

_API_BASE = "https://api.letsmesh.net/api"
_API_NODES_URL = f"{_API_BASE}/nodes"
_API_PACKETS_URL = f"{_API_BASE}/packets"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Origin": "https://analyzer.letsmesh.net",
    "Referer": "https://analyzer.letsmesh.net/",
}

_ROLE_MAP = {1: "CLI", 2: "REP", 3: "RMS", 4: "CLT"}


def _fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


class LetsmeshRestProvider:
    """REST client for api.letsmesh.net.

    Satisfies both NodeProvider and PacketProvider protocols.
    """

    def fetch_nodes(self, region: str) -> dict[str, dict]:
        """Fetch nodes. Returns dict keyed by 64-char hex public key."""
        data = _fetch_json(f"{_API_NODES_URL}?region={region}")
        nodes: dict[str, dict] = {}
        for n in data.get("nodes", []):
            key = n["public_key"].lower()
            nodes[key] = {
                "name": n["name"],
                "type": _ROLE_MAP.get(n.get("device_role"), str(n.get("device_role", ""))),
                "source": f"api:{region}",
                "key_complete": True,
                "last_seen": n.get("last_seen", ""),
            }
        return nodes

    def fetch_packets(self, region: str, limit: int = 50) -> list[dict]:
        """Fetch recent packets."""
        data = _fetch_json(f"{_API_PACKETS_URL}?region={region}&limit={limit}")
        if isinstance(data, list):
            return data
        return data.get("packets", [])
