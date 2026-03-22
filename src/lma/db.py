"""Node database: load, save, parse input files, and update from API."""

import json
import re
from pathlib import Path

from lma.api import DEFAULT_REGION, fetch_nodes

DB_FILE = Path(__file__).parent.parent.parent / "nodes.json"
INPUT_DIR = Path(__file__).parent.parent.parent / "input"


def load_db() -> dict:
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text())
    return {"nodes": {}}


def save_db(db: dict) -> None:
    DB_FILE.write_text(json.dumps(db, indent=2, sort_keys=True) + "\n")


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


def update(region: str = DEFAULT_REGION) -> None:
    db: dict = {"nodes": {}}

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
                    if k in ("type", "routing") and v
                }, "key_complete": True}
            else:
                db["nodes"][full_key] = api_node

    except Exception as e:
        print(f"  Warning: API fetch failed: {e}")

    save_db(db)
    print(f"Database updated: {len(db['nodes'])} total nodes -> {DB_FILE}")
