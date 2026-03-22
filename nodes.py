#!/usr/bin/env python3
"""
Meshcore node public key database.

Usage:
  nodes.py update [--region REGION]  - update database from input files and live API
  nodes.py lookup <hex_prefix>       - find node(s) by key prefix (1+ hex chars)
  nodes.py list [--by-key]           - list all nodes (default: sort by name)

The database is stored in nodes.json and built from:
  - input/*.txt  (static, manually maintained)
  - https://api.letsmesh.net/api/nodes (live, fetched on update)
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

DB_FILE = Path(__file__).parent / "nodes.json"
INPUT_DIR = Path(__file__).parent / "input"
API_URL = "https://api.letsmesh.net/api/nodes"
DEFAULT_REGION = "LUX"

ROLE_MAP = {1: "CLI", 2: "REP", 3: "RMS", 4: "CLT"}


def load_db():
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text())
    return {"nodes": {}}


def save_db(db):
    DB_FILE.write_text(json.dumps(db, indent=2, sort_keys=True) + "\n")


def parse_input_file(path):
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


def fetch_api_nodes(region):
    url = f"{API_URL}?region={region}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Origin": "https://analyzer.letsmesh.net",
            "Referer": "https://analyzer.letsmesh.net/",
        },
    )
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


def update(region=DEFAULT_REGION):
    db = {"nodes": {}}

    # Parse all input files
    for f in sorted(INPUT_DIR.glob("*.txt")):
        print(f"Parsing {f.name}...")
        file_nodes = parse_input_file(f)
        db["nodes"].update(file_nodes)
        print(f"  {len(file_nodes)} nodes")

    # Fetch from live API
    print(f"Fetching from API (region={region})...")
    try:
        api_nodes = fetch_api_nodes(region)
        print(f"  {len(api_nodes)} nodes")

        # Merge: for each API node (full key), check if an input partial key is a prefix of it.
        # If so, replace the partial entry with the full key, merging source data.
        partial_keys = {k: v for k, v in db["nodes"].items() if not v.get("key_complete")}

        for full_key, api_node in api_nodes.items():
            matched = next((pk for pk in partial_keys if full_key.startswith(pk)), None)
            if matched:
                partial_data = db["nodes"].pop(matched)
                # Prefer input file metadata (type, routing) but take full key from API
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


def lookup(prefix):
    prefix = prefix.lower().strip()
    if not re.fullmatch(r"[0-9a-f]+", prefix):
        print(f"Error: prefix must be hex characters, got: {prefix!r}")
        sys.exit(1)

    db = load_db()
    matches = [(k, v) for k, v in db["nodes"].items() if k.startswith(prefix)]

    if not matches:
        print(f"No nodes found with key prefix: {prefix}")
        sys.exit(1)

    for key, node in sorted(matches, key=lambda x: x[0]):
        partial = " [partial key]" if not node.get("key_complete") else ""
        last = f"  ({node['last_seen'][:10]})" if node.get("last_seen") else ""
        routing = f"  {node['routing']}" if node.get("routing") else ""
        print(f"{node['name']:<32}  {node.get('type', ''):4}  {key}{partial}{routing}{last}")


def list_nodes(by_key=False):
    db = load_db()
    if not db["nodes"]:
        print("No nodes in database. Run: nodes update")
        return
    if by_key:
        items = sorted(db["nodes"].items(), key=lambda x: x[0])
    else:
        items = sorted(db["nodes"].items(), key=lambda x: x[1]["name"].lower())
    for key, node in items:
        partial = "*" if not node.get("key_complete") else " "
        display_key = key[:16] + ("..." if len(key) > 16 else "")
        print(f"{node['name']:<32}  {node.get('type', ''):4}  {partial} {display_key}")
    total = len(db["nodes"])
    partial = sum(1 for v in db["nodes"].values() if not v.get("key_complete"))
    print(f"\n{total} nodes ({partial} with partial keys)")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    cmd = args[0]
    if cmd == "update":
        region = DEFAULT_REGION
        if "--region" in args:
            idx = args.index("--region")
            if idx + 1 < len(args):
                region = args[idx + 1]
        update(region)
    elif cmd == "lookup":
        if len(args) < 2:
            print("Usage: nodes lookup <hex_prefix>")
            sys.exit(1)
        lookup(args[1])
    elif cmd == "list":
        list_nodes(by_key="--by-key" in args)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
