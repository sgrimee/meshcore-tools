"""map.meshcore.dev API client — node coordinates lookup."""

import urllib.request

import msgpack

API_URL = "https://map.meshcore.dev/api/v1/nodes?binary=1&short=1"

# Abbreviated key mapping used by the short=1 response
_KEY_MAP = {
    "pk": "public_key",
    "n": "adv_name",
    "t": "type",
    "la": "last_advert",
    "id": "inserted_date",
    "ud": "updated_date",
    "p": "params",
    "l": "link",
    "s": "source",
}


def fetch_node_coords() -> dict[str, dict]:
    """Fetch node coordinates from map.meshcore.dev.

    Returns a dict keyed by lowercase 64-char hex public key, with values
    containing 'lat' and 'lon' floats. Only nodes with both coordinates included.
    """
    req = urllib.request.Request(API_URL)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = msgpack.unpackb(resp.read(), raw=False)

    coords: dict[str, dict] = {}
    nodes = data if isinstance(data, list) else data.get("nodes", [])
    for node in nodes:
        # Expand abbreviated keys
        expanded = {_KEY_MAP.get(k, k): v for k, v in node.items()}
        key = expanded.get("public_key", "")
        if isinstance(key, bytes):
            key = key.hex()
        else:
            key = str(key).lower()
        if len(key) != 64:
            continue
        lat = expanded.get("lat")
        lon = expanded.get("lon")
        if lat is not None and lon is not None and (float(lat) != 0.0 or float(lon) != 0.0):
            coords[key] = {"lat": float(lat), "lon": float(lon)}
    return coords
