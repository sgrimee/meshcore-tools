"""lma — letsmesh analyzer CLI entry point."""

import argparse
import sys

from lma.api import DEFAULT_REGION


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lma",
        description="letsmesh analyzer — node database and live packet monitor",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # --- nodes subcommand ---
    nodes_p = sub.add_parser("nodes", help="node database commands")
    nodes_sub = nodes_p.add_subparsers(dest="nodes_command", metavar="SUBCOMMAND")
    nodes_sub.required = True

    update_p = nodes_sub.add_parser("update", help="update database from input files and API")
    update_p.add_argument("--region", default=DEFAULT_REGION, metavar="REGION")

    lookup_p = nodes_sub.add_parser("lookup", help="find node(s) by public key prefix")
    lookup_p.add_argument("prefix", metavar="HEX_PREFIX")

    list_p = nodes_sub.add_parser("list", help="list all nodes")
    list_p.add_argument("--by-key", action="store_true", help="sort by public key instead of name")

    # --- monitor subcommand ---
    monitor_p = sub.add_parser("monitor", help="live packet monitoring TUI")
    monitor_p.add_argument("--region", default=DEFAULT_REGION, metavar="REGION")
    monitor_p.add_argument("--poll", type=int, default=5, metavar="SECONDS",
                           help="polling interval in seconds (default: 5)")

    args = parser.parse_args()

    if args.command == "nodes":
        if args.nodes_command == "update":
            from lma.db import update
            update(args.region)
        elif args.nodes_command == "lookup":
            from lma.nodes import lookup
            lookup(args.prefix)
        elif args.nodes_command == "list":
            from lma.nodes import list_nodes
            list_nodes(by_key=args.by_key)

    elif args.command == "monitor":
        from lma.monitor import run_monitor
        run_monitor(region=args.region, poll_interval=args.poll)


if __name__ == "__main__":
    main()
