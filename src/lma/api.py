"""letsmesh API client."""

import json
import urllib.request

DEFAULT_REGION = "LUX"
API_BASE = "https://api.letsmesh.net/api"
API_NODES_URL = f"{API_BASE}/nodes"
API_PACKETS_URL = f"{API_BASE}/packets"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Origin": "https://analyzer.letsmesh.net",
    "Referer": "https://analyzer.letsmesh.net/",
}

ROLE_MAP = {1: "CLI", 2: "REP", 3: "RMS", 4: "CLT"}


def fetch_nodes(region: str) -> dict[str, dict]:
    """Fetch nodes from the API. Returns dict keyed by 64-char hex public key."""
    url = f"{API_NODES_URL}?region={region}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    nodes = {}
    for n in data.get("nodes", []):
        key = n["public_key"].lower()
        nodes[key] = {
            "name": n["name"],
            "type": ROLE_MAP.get(n.get("device_role"), str(n.get("device_role", ""))),
            "source": f"api:{region}",
            "key_complete": True,
            "last_seen": n.get("last_seen", ""),
        }
    return nodes


def fetch_packets(region: str, limit: int = 50) -> list[dict]:
    """Fetch recent packets from the API."""
    url = f"{API_PACKETS_URL}?region={region}&limit={limit}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    if isinstance(data, list):
        return data
    return data.get("packets", [])
