# meshcore-tools

An unofficial terminal app for [MeshCore](https://meshcore.dev) LoRa mesh networks — monitor live packets with no hardware required, or connect directly to your node to chat, manage repeaters, and diagnose your mesh.

> **Work in progress.** The tool is usable but not complete — expect rough edges and missing features. [Open an issue](https://github.com/sgrimee/meshcore-tools/issues) if you hit a bug or have a feature request.

## Features

**Monitor mode** — no MeshCore device required
- **Live packet stream** — see every hop in real time, with relay hops resolved to node names
- **Message decryption** — supply your channel keys and GroupText messages are shown in plain text
- **Interactive map** — plot packet origins with SNR/RSSI overlay (optional `[map]` extra)
- **MQTT or letsmesh REST** as packet source — configurable in `settings.toml`
- **Expandable observer rows** — unfold a packet to see every individual observer report
- **Log panel** — toggle with `l`, resize with `+`/`-`, write to file with `--log-file`

**Companion mode** — requires a connected MeshCore node and the `[companion]` extra
- **Connect over TCP, Serial, or BLE** — auto-discovery, BLE scan, and recent-connection history
- **F2 Channels** — read and send group messages; import your channel keys to the device
- **F3 Contacts** — ping, DM, request telemetry/trace, login, and reboot contacts
- **F4 Device info** — firmware version, radio parameters, battery, and uptime at a glance
- **Saved passwords** — per-repeater and default login passwords in `~/.config/meshcore-tools/`
- **Unread indicators** — amber dot on tab labels when new messages arrive

**Node database CLI**
- Resolve short public-key prefixes to node names
- Populated from the letsmesh API and `map.meshcore.dev`
- Node blacklist in `settings.toml` to filter spurious or noisy nodes

## Screenshots

**F1 Monitor — live packets with relay-path resolution**

![Packet monitor with named relay path](assets/packets%20with%20name%20and%20hex%20path.png)

**Channels, Contacts, and Companion tabs**

| F2 Channels — group messaging with import | F3 Contacts — ping, DM, telemetry |
|---|---|
| ![Channels tab](assets/channels%20tab.png) | ![Contacts tab](assets/contacts%20tab.png) |

**F4 Companion device info**

![Companion info tab](assets/companion%20tab.png)

| Packet detail | Map view |
|---|---|
| ![Packet detail panel](assets/packet%20detail.png) | ![Map view](assets/map.png) |

## Installation

Requires [uv](https://docs.astral.sh/uv/).

### Install from git (no repo clone needed)

```sh
# Monitor only — no MeshCore device needed
uv tool install git+https://github.com/sgrimee/meshcore-tools

# With companion support (F2 Channels, F3 Contacts, F4 Device info)
uv tool install "meshcore-tools[companion] @ git+https://github.com/sgrimee/meshcore-tools"

# All features (companion + map rendering + MQTT source)
uv tool install "meshcore-tools[companion,map,mqtt] @ git+https://github.com/sgrimee/meshcore-tools"
```

### Install from a local clone

```sh
# Monitor only — no MeshCore device needed
uv tool install .

# With companion support (F2 Channels, F3 Contacts, F4 Device info)
uv tool install --extra companion .

# All features (companion + map rendering + MQTT source)
uv tool install --all-extras .
```

Then build the node database for the first time:

```sh
meshcore-tools nodes update
```

The default region is `LUX`. Pass `--region YOUR_REGION` or set it once in `settings.toml` — it is saved for future runs.

## Usage

```
meshcore-tools                                      launch full TUI (same as `monitor`)
meshcore-tools monitor [--region R] [--poll N] [--channels FILE] [--log-file FILE]
meshcore-tools nodes update [--region REGION]       refresh node database
meshcore-tools nodes lookup <hex_prefix>            find node by key prefix (1+ hex chars)
meshcore-tools nodes list [--by-key]                list all nodes
```

| Option | Default | Description |
|---|---|---|
| `--region` | saved or `LUX` | Region filter for the letsmesh API |
| `--poll` | `5` (letsmesh) / `1` (MQTT) | Polling interval in seconds |
| `--channels` | `channels.txt` if present | Channel key file for decryption |
| `--log-file` | — | Write debug log to a file in addition to the in-app panel |

### Examples

```sh
# Rebuild the node database
meshcore-tools nodes update

# Look up a node by first byte of public key
meshcore-tools nodes lookup 7d

# Look up by two bytes
meshcore-tools nodes lookup ab4b

# List all nodes sorted alphabetically
meshcore-tools nodes list

# List all nodes sorted by public key
meshcore-tools nodes list --by-key

# Start the TUI
meshcore-tools
```

### Monitor keybindings

| Key | Action |
|---|---|
| `d` | Toggle detail side panel |
| `shift+d` | Open detail popup |
| `m` | Toggle map side panel |
| `shift+m` | Open map popup |
| `b` | Toggle layout: right-stacked ↔ bottom side-by-side |
| `a` | Toggle follow mode (auto-scroll to newest packet) |
| `f` | Filter packets by observer or node in path |
| `n` | Cycle path display: names → src+hex → hex |
| `w` | Toggle path word-wrap |
| `p` | Pause / resume live updates |
| `r` | Force refresh |
| `c` | Clear packet list |
| `l` | Toggle log panel |
| `+` / `-` | Resize log panel |
| `C` | Open connection dialog |
| `q` | Quit |

**Side panels** update live as you move the cursor. Both panels can be open at the same time. Use `b` to switch between panels stacked on the right (default) or placed side by side at the bottom of the screen.

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

If you have a connected device, you can also import your local `channels.txt` keys directly to it from the **F2 Channels tab** using the Import button.

See `channels.txt.sample` for a template.

## Companion features

Companion features require the `[companion]` extra and a connected MeshCore device. Press `C` from anywhere in the TUI to open the connection dialog.

### Connecting

Three transport types are supported:

| Transport | How to connect |
|---|---|
| **TCP** | Enter host and port (e.g. `192.168.1.10:5000`) |
| **Serial** | Select from auto-discovered `/dev/tty*` / `COMx` ports |
| **BLE** | Scan for nearby devices; enter a PIN if pairing is required |

Recent connections are shown expanded by default. The last successful connection is auto-restored on the next launch.

### F2 Channels tab

- Channel list on the left, message log and input on the right
- Use `←` / `→` to switch channels
- Send messages up to 133 characters
- **Import channels** button pushes your local `channels.txt` keys to the device
- New incoming messages trigger an amber unread dot on the tab label

### F3 Contacts tab

- Contact list on the left; contextual actions on the right based on contact type
- Available actions: **Ping**, **DM** (direct message), **Status**, **Telemetry**, **Trace**, **Login**, **Reboot**
- Login prompts for a password and saves it if successful (see Password management below)
- Unread DMs show an amber dot on the tab label

### F4 Companion info tab

Shows device name, public key, firmware version, battery level, uptime, and LoRa radio parameters (frequency, bandwidth, spreading factor, TX power, coding rate). Includes a free-form command input for advanced use.

### Password management

Passwords are stored with `600` permissions under `~/.config/meshcore-tools/`:

- `settings.toml` — `default_password` field; used as a fallback for all logins
- `passwords.toml` — per-repeater passwords keyed by public key; take precedence over the default

Saved passwords are pre-filled in the login dialog automatically.

## Configuration

Settings live in `$XDG_CONFIG_HOME/meshcore-tools/settings.toml` (defaults to `~/.config/meshcore-tools/settings.toml` on Linux and macOS). The file is created automatically when you first save a region or password. Example:

```toml
[general]
region = "LUX"

[filtering]
blacklist = ["deadbeef", "cafebabe"]   # public-key prefixes or name substrings to hide

[packet_source]
type = "mqtt"   # "letsmesh" (default) or "mqtt"

[mqtt]
broker = "localhost"
port = 1883
topic = "meshcore/raw"
# username = "..."
# password = "..."
```

| Key | Default | Description |
|---|---|---|
| `general.region` | `LUX` | Default region for API queries |
| `filtering.blacklist` | `[]` | Name substrings or key prefixes to suppress in the monitor |
| `packet_source.type` | `letsmesh` | Packet source: `letsmesh` or `mqtt` |
| `mqtt.broker` | `localhost` | MQTT broker hostname |
| `mqtt.port` | `1883` | MQTT broker port |
| `mqtt.topic` | `meshcore/raw` | MQTT topic pattern |
| `mqtt.username` / `mqtt.password` | — | Optional MQTT credentials |

## Node database

The database is stored in `nodes.json` (gitignored, auto-generated). Run `meshcore-tools nodes update` to create or refresh it.

## Data sources

### Input files (`input/*.txt`)

The live APIs only know nodes that have been seen recently. Input files let you register your own nodes — and nodes of friends — so they are always resolvable by name in the monitor, even if they haven't appeared in the API data yet. Short key prefixes are accepted, so you don't need the full 64-char public key; on `nodes update` they are matched against the API data and upgraded automatically.

The easiest way to populate a file is to copy-paste the output of `list contacts` from [meshcore-cli](https://github.com/ripplingwaves/meshcore-cli). Format (one node per line):

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

On `meshcore-tools nodes update`, the tool fetches data from two sources:

- **letsmesh** (`api.letsmesh.net`) — node list for the region; partial keys from input files are matched and upgraded to full 64-char keys. Use `--region` to select a region (default: `LUX`).
- **map.meshcore.dev** — node coordinates (lat/lon); backfills any node in the database that lacks coordinates.

## Contributing and issues

This is an unofficial project. Bug reports, feature requests, and pull requests are welcome.

- **Report a bug or request a feature:** [github.com/sgrimee/meshcore-tools/issues](https://github.com/sgrimee/meshcore-tools/issues)
- For non-trivial pull requests, please open an issue first to discuss the approach.
- Dev setup: `uv sync --all-extras` — see `CLAUDE.md` for contributor notes.

## Credits

- [letsmesh analyzer](https://analyzer.letsmesh.net) — packet analysis and node list API (`api.letsmesh.net`)
- [MeshCore](https://meshcore.dev) — firmware and node map API (`map.meshcore.dev`)
- [meshcore-cli](https://github.com/ripplingwaves/meshcore-cli) — CLI for interacting with MeshCore nodes
- [meshcore_py](https://github.com/fdlamotte/meshcore_py) — Python library for companion connectivity (`meshcore` PyPI package)
