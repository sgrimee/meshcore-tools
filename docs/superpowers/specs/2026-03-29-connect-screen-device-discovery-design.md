# ConnectScreen Device Discovery Design

**Date:** 2026-03-29
**Status:** Approved

## Problem

`ConnectScreen` requires users to manually type serial device paths and BLE device names. Connecting via BLE without a name causes a permissions error (BlueZ/DBus) with no helpful feedback.

## Goal

- Serial: show a list of available ports from `serial.tools.list_ports`
- BLE: scan for nearby `MeshCore-*` devices with a spinner, show results in a `Select`
- Handle BLE permission errors gracefully with an actionable message

## Scope

All changes in `src/meshcore_tools/connection.py`. No new files. No changes to `ConnectionConfig` schema.

## Architecture

`ConnectScreen` is reorganised into three mutually exclusive content sections that mount/unmount based on the selected connection type:

| Type   | Section ID       | Contents |
|--------|------------------|----------|
| TCP    | `#tcp-section`   | host `Input` + port `Input` (unchanged) |
| Serial | `#serial-section`| `Select` of ports + "Refresh" button |
| BLE    | `#ble-section`   | "Scan" button → `LoadingIndicator` → `Select` of devices |

`on_select_changed` for `#conn_type` unmounts the previous section and mounts the new one.

## Data Flow

### Serial
1. On `compose()`, call `serial.tools.list_ports.comports()` synchronously (fast, <10ms).
2. Populate `Select` with `(description — port, port)` sorted by port name.
3. "Refresh" button re-runs the same call.
4. On Connect: `ConnectionConfig(type="serial", device=<selected_port>)`.

### BLE
1. "Scan" button triggers a Textual `@work` async worker running `BleakScanner.discover(timeout=5.0)`.
2. While scanning: hide Scan button, show `LoadingIndicator`.
3. On success with results: show `Select` with `(name — address, name)` for devices whose name starts with `"MeshCore"`.
4. On success with no results: show "No MeshCore devices found" label + re-enable Scan button.
5. On `BleakDBusError` / `BleakError`: show inline error label: `"Bluetooth error: <msg>. Try: sudo usermod -aG bluetooth $USER"` + re-enable Scan button.
6. On Connect: `ConnectionConfig(type="ble", ble_name=<selected_name>)`.

### TCP
Unchanged. `ConnectionConfig(type="tcp", host=<host>, port=<port>)`.

## Visual Layout

Modal width: 60 chars (unchanged).

**BLE (scanning):**
```
┌──────────────────────────────────────────────────────────┐
│  Connect to companion device                             │
│  Connection type: [ BLE                            ▼ ]  │
│                                                          │
│  ◌ Scanning...                                          │
│                                                          │
│  [ Connect ]  [ Cancel ]                                 │
└──────────────────────────────────────────────────────────┘
```

**BLE (results):**
```
│  [ MeshCore-abc123 (AA:BB:CC:DD:EE:FF)             ▼ ]  │
```

**Serial:**
```
│  [ /dev/ttyUSB0 — CP2102 USB to UART               ▼ ]  │
│  [ Refresh ]                                             │
```

## Connect Button State

The Connect button is disabled until:
- TCP: host field is non-empty
- Serial: a port is selected
- BLE: a device is selected from scan results

## Error Handling

| Scenario | Response |
|----------|----------|
| No serial ports found | `Select` shows "No ports found" (disabled), Connect disabled |
| No BLE devices found | Label "No MeshCore devices found", Scan button re-enabled |
| `BleakDBusError` / `BleakError` | Label with error + `sudo usermod -aG bluetooth $USER` hint |
| `bleak` not installed | "BLE requires bleak: pip install meshcore-tools[companion]" |

## Dependencies

- `serial.tools.list_ports` — already available via `pyserial` (transitive dep of `meshcore`)
- `bleak.BleakScanner` — already available when companion extra is installed; guarded by `BLEAK_AVAILABLE` flag from `meshcore.ble_cx`
