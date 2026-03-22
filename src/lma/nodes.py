"""Node subcommand: lookup and list nodes from the local database."""

import re
import sys

from lma.db import load_db


def lookup(prefix: str) -> None:
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


def list_nodes(by_key: bool = False) -> None:
    db = load_db()
    if not db["nodes"]:
        print("No nodes in database. Run: lma nodes update")
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
    partial_count = sum(1 for v in db["nodes"].values() if not v.get("key_complete"))
    print(f"\n{total} nodes ({partial_count} with partial keys)")
