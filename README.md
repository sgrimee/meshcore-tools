# meshcore-nodes

A CLI tool to maintain a database of MeshCore node public keys and look up node names by key prefix.

## Usage

```
nodes update [--region REGION]   update database from input files and live API
nodes lookup <hex_prefix>        find node(s) by key prefix (1+ hex chars)
nodes list [--by-key]            list all nodes (default: sort by name)
```

### Examples

```sh
# Rebuild the database
nodes update

# Look up by first byte of public key
nodes lookup 7d

# Look up by two bytes
nodes lookup ab4b

# List all nodes sorted alphabetically
nodes list

# List all nodes sorted by public key
nodes list --by-key
```

## Data sources

### Input files (`input/*.txt`)

Static node lists maintained manually. Format (one node per line):

```
name   TYPE   pubkey_hex   [routing]
```

- `name` — node name
- `TYPE` — `CLI` (client) or `REP` (repeater)
- `pubkey_hex` — hex public key, full 64 chars or a shorter prefix
- `routing` — optional, e.g. `Flood` or `0 hop`

Lines may optionally be prefixed with a line number (`1→`).

### Live API

On `nodes update`, the tool fetches node data from `https://api.letsmesh.net/api/nodes`.
Use `--region` to fetch a different region (default: `LUX`).

Partial keys from input files are automatically matched and upgraded to full 32-byte keys when the API returns a matching node.

## Database

The database is stored in `nodes.json` (gitignored, auto-generated). Run `nodes update` to create or refresh it.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run nodes update
```

Or install as a tool:

```sh
uv tool install .
nodes update
```
