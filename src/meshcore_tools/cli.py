"""meshcore-tools — CLI entry point."""

import argparse
import os

from meshcore_tools.providers.letsmesh_rest import DEFAULT_REGION


def _resolve_region(explicit: str | None) -> str:
    """Return the region to use, saving it to config when explicitly provided."""
    from meshcore_tools.config import get_region, save_region
    if explicit is not None:
        save_region(explicit)
        return explicit
    saved = get_region()
    return saved if saved is not None else DEFAULT_REGION


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="meshcore-tools",
        description="meshcore tools — node database and live packet monitor",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = False  # no subcommand → launch MeshCoreApp

    # --- nodes subcommand ---
    nodes_p = sub.add_parser("nodes", help="node database commands")
    nodes_sub = nodes_p.add_subparsers(dest="nodes_command", metavar="SUBCOMMAND")
    nodes_sub.required = True

    update_p = nodes_sub.add_parser("update", help="update database from input files and API")
    update_p.add_argument("--region", default=None, metavar="REGION")

    lookup_p = nodes_sub.add_parser("lookup", help="find node(s) by public key prefix")
    lookup_p.add_argument("prefix", metavar="HEX_PREFIX")

    list_p = nodes_sub.add_parser("list", help="list all nodes")
    list_p.add_argument("--by-key", action="store_true", help="sort by public key instead of name")

    # --- monitor subcommand (alias for default TUI) ---
    monitor_p = sub.add_parser("monitor", help="live packet monitoring TUI (default)")
    monitor_p.add_argument("--region", default=None, metavar="REGION")
    monitor_p.add_argument("--poll", type=int, default=5, metavar="SECONDS",
                           help="polling interval in seconds (default: 5)")
    monitor_p.add_argument("--channels", metavar="FILE", default=None,
                           help="channel keys file for decryption (default: channels.txt if present)")
    monitor_p.add_argument("--log-file", metavar="FILE", default=None,
                           help="write logs to FILE in addition to the in-app Logs tab")

    args = parser.parse_args()

    if args.command == "nodes":
        if args.nodes_command == "update":
            from meshcore_tools.db import update
            from meshcore_tools.providers.letsmesh_rest import LetsmeshRestProvider
            from meshcore_tools.providers.meshcore_rest import MeshcoreRestProvider
            update(_resolve_region(args.region), node_provider=LetsmeshRestProvider(), coord_provider=MeshcoreRestProvider())
        elif args.nodes_command == "lookup":
            from meshcore_tools.nodes import lookup
            lookup(args.prefix)
        elif args.nodes_command == "list":
            from meshcore_tools.nodes import list_nodes
            list_nodes(by_key=args.by_key)

    else:
        # Default (no subcommand) and "monitor" both launch MeshCoreApp
        region = _resolve_region(getattr(args, "region", None))
        poll = getattr(args, "poll", 5)
        channels = getattr(args, "channels", None)
        if channels is None and os.path.exists("channels.txt"):
            channels = "channels.txt"
        log_file = getattr(args, "log_file", None)
        if log_file:
            import logging
            fh = logging.FileHandler(log_file, mode="a")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
            logging.getLogger().addHandler(fh)
            logging.getLogger().setLevel(logging.DEBUG)
        from meshcore_tools.app import MeshCoreApp
        from meshcore_tools.providers.letsmesh_rest import LetsmeshRestProvider
        MeshCoreApp(
            region=region,
            packet_provider=LetsmeshRestProvider(),
            poll_interval=poll,
            channels_path=channels,
        ).run()


if __name__ == "__main__":
    main()
