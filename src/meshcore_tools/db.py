"""Node database: load, save, parse input files, and update from API."""

import json
import re
from pathlib import Path

from meshcore_tools.letsmesh_api import DEFAULT_REGION, fetch_nodes
from meshcore_tools.meshcore_api import fetch_node_coords

_ADVERT_ROLE_SHORT = {
    "ChatNode": "CLI", "Repeater": "REP", "RoomServer": "RMS", "Sensor": "CLT",
}

DB_FILE = Path(__file__).parent.parent.parent / "nodes.json"
INPUT_DIR = Path(__file__).parent.parent.parent / "input"


def load_db() -> dict:
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text())
    return {"nodes": {}}


def save_db(db: dict) -> None:
    tmp = DB_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, indent=2, sort_keys=True) + "\n")
    tmp.replace(DB_FILE)


def learn_from_advert(
    db: dict,
    public_key: str,
    name: str,
    role: str,
    lat: float | None = None,
    lon: float | None = None,
) -> bool:
    """Add or update a node learned from a live Advert packet.

    Returns True if the database was modified (caller should save).
    Never overwrites hand-curated input-file entries (source not api:/advert).
    """
    key = public_key.lower()
    if len(key) != 64:
        return False
    short_role = _ADVERT_ROLE_SHORT.get(role, role)
    existing = db["nodes"].get(key)
    if existing:
        source = existing.get("source", "")
        if not source.startswith(("api:", "advert")):
            return False  # don't overwrite hand-curated entries
        if (existing.get("name") == name
                and existing.get("type") == short_role
                and existing.get("lat") == lat
                and existing.get("lon") == lon):
            return False  # nothing changed
    entry: dict = {
        "name": name,
        "type": short_role,
        "source": "advert",
        "key_complete": True,
    }
    if lat is not None and lon is not None and (lat != 0.0 or lon != 0.0):
        entry["lat"] = lat
        entry["lon"] = lon
    db["nodes"][key] = entry
    return True


def parse_input_file(path) -> dict[str, dict]:
    """Parse input file format: [N→]name  type  pubkey_hex  [routing...]"""
    nodes = {}
    for line in Path(path).read_text().splitlines():
        line = re.sub(r"^\s*\d+→", "", line).strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        name, type_, key = parts[0], parts[1], parts[2].lower()
        routing = " ".join(parts[3:]) if len(parts) > 3 else ""
        if not re.fullmatch(r"[0-9a-f]+", key):
            continue
        nodes[key] = {
            "name": name,
            "type": type_,
            "routing": routing,
            "source": Path(path).name,
            "key_complete": len(key) == 64,
        }
    return nodes


def is_input_node(node_id: str, db: dict) -> bool:
    """Return True if node_id matches an input-file entry (user-owned node)."""
    node_id = node_id.lower()
    for key, entry in db.get("nodes", {}).items():
        if key.startswith(node_id) or node_id.startswith(key[: len(node_id)]):
            source = entry.get("source", "")
            if source and not source.startswith(("api:", "advert")):
                return True
    return False


def resolve_name(origin_id: str, db: dict) -> str:
    """Resolve a key prefix to a display name.

    Returns the node name if unambiguous, 'name1/name2?' if multiple matches,
    or the raw 8-char prefix if no match found.
    """
    origin_id = origin_id.lower()
    names = [
        db["nodes"][key]["name"]
        for key in db.get("nodes", {})
        if key.startswith(origin_id) or origin_id.startswith(key[: len(origin_id)])
    ]
    if not names:
        return origin_id[:8]
    if len(names) == 1:
        return names[0]
    return "/".join(names) + "?"


def update(region: str = DEFAULT_REGION) -> None:
    # Seed with advert-learned nodes so they survive if not in API/input files
    existing = load_db()
    advert_nodes = {k: v for k, v in existing["nodes"].items()
                    if v.get("source") == "advert"}
    db: dict = {"nodes": dict(advert_nodes)}

    for f in sorted(INPUT_DIR.glob("*.txt")):
        print(f"Parsing {f.name}...")
        file_nodes = parse_input_file(f)
        db["nodes"].update(file_nodes)
        print(f"  {len(file_nodes)} nodes")

    print(f"Fetching from API (region={region})...")
    try:
        api_nodes = fetch_nodes(region)
        print(f"  {len(api_nodes)} nodes")

        partial_keys = {k: v for k, v in db["nodes"].items() if not v.get("key_complete")}

        for full_key, api_node in api_nodes.items():
            matched = next((pk for pk in partial_keys if full_key.startswith(pk)), None)
            if matched:
                partial_data = db["nodes"].pop(matched)
                db["nodes"][full_key] = {**api_node, **{
                    k: v for k, v in partial_data.items()
                    if k in ("type", "routing", "source") and v
                }, "key_complete": True}
            else:
                db["nodes"][full_key] = api_node

    except Exception as e:
        print(f"  Warning: API fetch failed: {e}")

    print("Fetching coordinates from map.meshcore.dev...")
    try:
        coords = fetch_node_coords()
        print(f"  {len(coords)} nodes with coordinates")
        filled = 0
        for key, node in db["nodes"].items():
            if "lat" not in node and key in coords:
                node["lat"] = coords[key]["lat"]
                node["lon"] = coords[key]["lon"]
                filled += 1
        print(f"  {filled} nodes backfilled with coordinates")
    except Exception as e:
        print(f"  Warning: meshcore.dev coord fetch failed: {e}")

    save_db(db)
    print(f"Database updated: {len(db['nodes'])} total nodes -> {DB_FILE}")
