# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See README.md for usage, commands, input file format, and data sources.

## Architecture

The entire tool is a single file: `nodes.py`, exposed as the `nodes` CLI entry point via `[project.scripts]` in `pyproject.toml`. No third-party dependencies.

**Data flow:** `input/*.txt` + live API → `nodes.json` (gitignored)

**Merge logic (`update()`):** Input file nodes with partial keys (< 64 hex chars) are matched against API nodes whose full key starts with that partial. On match, the partial entry is replaced with the full 64-char key, preserving `type` and `routing` from the input file.

**API access:** `https://api.letsmesh.net/api/nodes?region=LUX` requires `Origin: https://analyzer.letsmesh.net` — no auth, undocumented backend of the Angular frontend.

**`nodes.json` schema per node:**
```json
{
  "name": "gw-charly",
  "type": "CLI",
  "routing": "Flood",
  "source": "sam.txt",
  "key_complete": true,
  "last_seen": "2026-03-06T..."
}
```
`source` is either a filename from `input/` or `"api:REGION"`. `last_seen` is only present for API-sourced nodes.
