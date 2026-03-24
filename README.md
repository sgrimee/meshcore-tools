# meshcore-nodes

An unofficial CLI client for the [letsmesh analyzer](https://analyzer.letsmesh.net) — maintains a local database of MeshCore node public keys and lets you look up node names by key prefix.

## Screenshots

**Live packet monitor** — resolves relay hops to node names, shows SNR/RSSI, and highlights selected packets

![Packet monitor with named relay path](assets/packets%20with%20name%20and%20hex%20path.png)

| Packet detail | Map view |
|---|---|
| ![Packet detail panel](assets/packet%20detail.png) | ![Map view](assets/map.png) |

## Usage

```
lma nodes update [--region REGION]   update database from input files and APIs
lma nodes lookup <hex_prefix>        find node(s) by key prefix (1+ hex chars)
lma nodes list [--by-key]            list all nodes (default: sort by name)
lma monitor [--region REGION] [--poll SECONDS] [--channels FILE]   live packet monitoring TUI
```

### Examples

```sh
# Rebuild the database
lma nodes update

# Look up by first byte of public key
lma nodes lookup 7d

# Look up by two bytes
lma nodes lookup ab4b

# List all nodes sorted alphabetically
lma nodes list

# List all nodes sorted by public key
lma nodes list --by-key

# Start live packet monitor
lma monitor
```

### Monitor keybindings

| Key | Action |
|---|---|
| `d` | Toggle detail side panel |
| `shift+d` | Open detail popup |
| `m` | Toggle map side panel |
| `shift+m` | Open map popup |
| `l` | Toggle panel layout: right-stacked ↔ bottom side-by-side |
| `a` | Toggle follow mode (auto-scroll to newest packet) |
| `f` | Filter packets by observer or node in path |
| `n` | Cycle path display: names → src+hex → hex |
| `w` | Toggle path word-wrap |
| `p` | Pause / resume live updates |
| `r` | Force refresh |
| `c` | Clear packet list |
| `q` | Quit |

**Side panels** update live as you move the cursor. Both panels can be open at the same time. With `l`, switch between panels stacked on the right (default) or placed side by side at the bottom of the screen.

**Follow mode** (`a`) is off by default — the cursor stays on the selected packet while new packets arrive in the background. Turn it on to auto-scroll to the newest packet.

**Input-file nodes** (from `input/*.txt`) are highlighted in yellow in the path column and detail panel, making it easy to spot your own nodes in packet paths.

### Channel decryption

The monitor can decrypt GroupText messages if you supply a channels file with the channel keys. Create `channels.txt` in the working directory (gitignored) by appending the output of `get_channels` from [meshcore-cli](https://github.com/ripplingwaves/meshcore-cli):

```sh
just get-channels               # uses first available device
just get-channels /dev/ttyUSB0  # specify device explicitly
```

The output is used directly — no editing required:

```
0: Public [8b3387e9c5cdea6ac9e5edbaa115cd72]
1: #wardriving [e3c26491e9cd321e3a6be50d57d54acf]
2: #chaosstuff [b53025e867806e0b5e241adc0d47358b]
```

Hashtag channels may also be listed without a key (the key is derived automatically from the channel name):

```
#luxembourg
```

The file is loaded automatically if it exists as `channels.txt`, or you can specify a path with `--channels FILE`. When a message is successfully decrypted, the sender name and message text are shown in the detail panel instead of "encrypted".

See `channels.txt.sample` for a template.

## Data sources

### Input files (`input/*.txt`)

Static node lists maintained manually. The easiest way to populate one is to copy-paste the output of `list contacts` from [meshcore-cli](https://github.com/ripplingwaves/meshcore-cli). Format (one node per line):

```
name   TYPE   pubkey_hex   [routing]
```

- `name` — node name
- `TYPE` — `CLI` (client) or `REP` (repeater)
- `pubkey_hex` — hex public key, full 64 chars or a shorter prefix
- `routing` — optional, e.g. `Flood` or `0 hop`

Lines may optionally be prefixed with a line number (`1→`).

See `input/example.txt.sample` for a sample. Copy it to a new `.txt` file in the same directory and edit it with your own nodes.

### Live APIs

On `lma nodes update`, the tool fetches data from two sources:

- **letsmesh** (`api.letsmesh.net`) — node list for the region; partial keys from input files are matched and upgraded to full 64-char keys. Use `--region` to select a region (default: `LUX`).
- **map.meshcore.dev** — node coordinates (lat/lon); backfills any node in the database that lacks coordinates.

## Database

The database is stored in `nodes.json` (gitignored, auto-generated). Run `nodes update` to create or refresh it.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync --all-extras
uv run lma nodes update
```

Or install as a tool:

```sh
uv tool install --all-extras .
lma nodes update
```

## Credits

- [letsmesh analyzer](https://analyzer.letsmesh.net) — packet analysis and node list API (`api.letsmesh.net`)
- [MeshCore](https://meshcore.dev) — firmware and node map API (`map.meshcore.dev`)
- [meshcore-cli](https://github.com/ripplingwaves/meshcore-cli) — CLI for interacting with MeshCore nodes
