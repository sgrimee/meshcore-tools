"""CompanionManager — bridges meshcore async client to Textual's event loop.

Import guard: this module imports meshcore at the top level.
Only import it inside `try/except ImportError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import logging

from textual.message import Message

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from textual.app import App
    from meshcore_tools.connection import ConnectionConfig

# meshcore is an optional dependency — imported lazily inside connect()
try:
    from meshcore import MeshCore, EventType as _EventType
    _MESHCORE_AVAILABLE = True
except ImportError:
    _MESHCORE_AVAILABLE = False
    _EventType = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SELF_CMD_HELP = "available commands: ver, infos, bat, time, advert, device, reboot"


def _result_or_error(result: Any, ok: str | None = None) -> str:
    """Return the result payload, or an error string if the result is an error event."""
    if str(getattr(result, "type", "")) == str(_EventType.ERROR):
        return f"error: {result.payload}"
    return ok if ok is not None else str(result.payload)


# ---------------------------------------------------------------------------
# Custom Textual messages posted to the app from CompanionManager callbacks
# ---------------------------------------------------------------------------

class CompanionConnected(Message):
    """Posted when the companion device connects and sends self-info."""

    def __init__(self, node_name: str, node_key: str, self_info: dict | None = None) -> None:
        super().__init__()
        self.node_name = node_name
        self.node_key = node_key
        self.self_info: dict = self_info or {}


class CompanionDisconnected(Message):
    """Posted when the companion device disconnects cleanly."""


class CompanionConnectionError(Message):
    """Posted when a connection attempt fails."""

    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason


class ChannelMessage(Message):
    """Posted when a channel broadcast message is received."""

    def __init__(
        self,
        channel_idx: int,
        channel_name: str,
        sender: str,
        text: str,
        timestamp: int,
    ) -> None:
        super().__init__()
        self.channel_idx = channel_idx
        self.channel_name = channel_name
        self.sender = sender
        self.text = text
        self.timestamp = timestamp


class ContactMessage(Message):
    """Posted when a direct message from a contact is received."""

    def __init__(
        self, pubkey_prefix: str, sender: str, text: str, timestamp: int
    ) -> None:
        super().__init__()
        self.pubkey_prefix = pubkey_prefix
        self.sender = sender
        self.text = text
        self.timestamp = timestamp


class ContactLoginChanged(Message):
    """Posted when a contact login succeeds or fails."""

    def __init__(self, pubkey_prefix: str, success: bool) -> None:
        super().__init__()
        self.pubkey_prefix = pubkey_prefix
        self.success = success


class ContactsUpdated(Message):
    """Posted when the contacts list is fetched or refreshed."""

    def __init__(self, contacts: list[dict]) -> None:
        super().__init__()
        self.contacts = contacts


class ChannelsUpdated(Message):
    """Posted when the device channels are fetched after connecting."""

    def __init__(self, channels: list[dict]) -> None:
        super().__init__()
        self.channels = channels


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------

def _ble_error_message(exc: Exception) -> str:
    """Return a plain-English error message for common BLE/connection failures."""
    msg = str(exc)
    if "NotPermitted" in msg:
        return (
            "BLE: notification channel busy — stale connection could not be cleared. "
            "Try: bluetoothctl disconnect <address>, or restart Bluetooth."
        )
    if "NotFound" in msg or "DeviceNotFound" in msg:
        return "BLE device not found. Is it turned on and in range?"
    if "NotConnected" in msg:
        return "BLE connection lost. Try again."
    # Strip noisy BlueZ DBus prefix for everything else
    if "org.bluez.Error" in msg:
        return f"BLE error: {msg.split('] ', 1)[-1]}" if '] ' in msg else f"BLE error: {msg}"
    return msg


def _extract_channel_key_hex(payload: dict) -> str:
    """Extract a 16-byte AES key from a get_channel payload dict.

    Tries the field names used by known meshcore firmware versions.
    Returns a 32-char lowercase hex string, or '' if no key material is found.
    """
    for field in ("key", "aes_key", "channel_key", "secret", "channel_secret"):
        raw = payload.get(field)
        if raw is None:
            continue
        if isinstance(raw, (bytes, bytearray)) and len(raw) == 16:
            if not any(raw):  # all-zero = unconfigured slot
                continue
            return raw.hex()
        if isinstance(raw, str) and len(raw) == 32:
            try:
                bytes.fromhex(raw)  # validate
                return raw.lower()
            except ValueError:
                pass
    return ""


async def _ble_flush_stale(address: str) -> None:
    """Connect to a BLE device and disconnect immediately.

    This forces BlueZ to close any abandoned connection left by a previous
    failed attempt (ble_cx.py does not call disconnect() when start_notify
    raises NotPermitted, leaving the BleakClient connected but unusable).
    """
    try:
        from bleak import BleakScanner, BleakClient

        if ":" in address:
            device = await BleakScanner.find_device_by_address(address, timeout=5.0)
        else:
            def _match(d, _):
                return bool(d.name and address in d.name)
            device = await BleakScanner.find_device_by_filter(_match, timeout=5.0)

        if device:
            client = BleakClient(device)
            await client.connect()
            await client.disconnect()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CompanionManager — async bridge
# ---------------------------------------------------------------------------

class CompanionManager:
    """Manages the meshcore async client and posts Textual messages to the app.

    Runs in Textual's asyncio event loop (no threads needed).
    Usage:
        manager = CompanionManager(app)
        await manager.connect(config)       # auto-called on startup
        await manager.disconnect()
        # Outgoing commands: called via @work(thread=False) on the widget
        await manager.send_channel_message(channel_idx, text)
        await manager.send_repeater_status(contact)
        await manager.send_repeater_login(contact, password)
        await manager.send_repeater_cmd(contact, cmd)
        await manager.send_repeater_trace(contact)
        await manager.send_repeater_reboot(contact)
    """

    def __init__(self, app: App) -> None:
        self._app = app
        self._client: Any = None  # MeshCore instance
        self._contacts: list[Any] = []
        self._connected = False

    async def connect(self, config: ConnectionConfig) -> None:
        """Establish meshcore connection and subscribe to push events."""
        if not _MESHCORE_AVAILABLE:
            self._app.post_message(
                CompanionConnectionError(reason="meshcore package not installed")
            )
            return

        logger.info("Connecting companion (%s)", config.type)
        try:
            if config.type == "tcp":
                self._client = await MeshCore.create_tcp(
                    config.host or "127.0.0.1",
                    config.port or 5000,
                )
            elif config.type == "serial":
                self._client = await MeshCore.create_serial(config.device or "")
            elif config.type == "ble":
                ble_addr = config.ble_address or config.ble_name or ""
                # Use a freshly scanned BLEDevice when available (set by
                # ConnectScreen after a manual scan) — this is more reliable
                # than connecting by MAC address alone, because BlueZ may not
                # have the device in its cache on startup.
                ble_device = getattr(config, "ble_device", None)
                try:
                    if ble_device is not None:
                        self._client = await MeshCore.create_ble(
                            device=ble_device, pin=config.ble_pin
                        )
                    else:
                        self._client = await MeshCore.create_ble(
                            ble_addr, pin=config.ble_pin
                        )
                except Exception as exc:
                    if "NotPermitted" not in str(exc):
                        raise
                    # Stale BleakClient left connected by previous failed attempt.
                    # Flush it and retry once.
                    await _ble_flush_stale(ble_addr)
                    self._client = await MeshCore.create_ble(
                        ble_addr, pin=config.ble_pin
                    )
            else:
                self._app.post_message(
                    CompanionConnectionError(reason=f"unknown type: {config.type}")
                )
                return
        except Exception as exc:
            reason = _ble_error_message(exc)
            logger.warning("Companion connection error: %s", reason)
            self._app.post_message(CompanionConnectionError(reason=reason))
            return

        self._connected = True
        self._subscribe_events()
        await self._fetch_contacts()
        await self._fetch_channels()
        await self._client.start_auto_message_fetching()

        logger.info("Companion connected")
        self_info = self._client.self_info or {}
        node_name = self_info.get("name", "companion")
        node_key = self_info.get("public_key", "")
        self._app.post_message(
            CompanionConnected(node_name=node_name, node_key=node_key, self_info=self_info)
        )

    def _subscribe_events(self) -> None:
        client = self._client

        async def _on_channel_msg(event) -> None:
            d = event.payload
            self._app.post_message(
                ChannelMessage(
                    channel_idx=int(d.get("channel_idx", 0)),
                    channel_name=f"#{d.get('channel_idx', 0)}",
                    sender=d.get("sender", "unknown"),
                    text=d.get("text", ""),
                    timestamp=int(d.get("timestamp", 0)),
                )
            )

        async def _on_contact_msg(event) -> None:
            d = event.payload
            pubkey_prefix = d.get("pubkey_prefix", "")
            sender = d.get("sender", pubkey_prefix) or pubkey_prefix
            # If sender looks like a hex address, resolve it to a contact name
            if sender and all(c in "0123456789abcdefABCDEF" for c in sender):
                for c in self._contacts:
                    pk = c.get("public_key", "") or ""
                    if pk.startswith(sender) or sender.startswith(pk[:len(sender)]):
                        sender = c.get("adv_name") or c.get("name") or sender
                        break
            self._app.post_message(
                ContactMessage(
                    pubkey_prefix=pubkey_prefix,
                    sender=sender or "?",
                    text=d.get("text", ""),
                    timestamp=int(d.get("timestamp", 0)),
                )
            )

        async def _on_disconnected(event) -> None:
            self._connected = False
            logger.debug("Companion disconnected")
            self._app.post_message(CompanionDisconnected())

        async def _on_login_success(event) -> None:
            prefix = event.payload.get("pubkey_prefix", "")
            self._app.post_message(ContactLoginChanged(pubkey_prefix=prefix, success=True))

        async def _on_login_failed(event) -> None:
            prefix = event.payload.get("pubkey_prefix", "")
            self._app.post_message(ContactLoginChanged(pubkey_prefix=prefix, success=False))

        async def _on_any_event(event) -> None:
            logger.debug(
                "companion event: type=%s attrs=%s payload=%s",
                event.type,
                event.attributes,
                event.payload,
            )

        client.subscribe(_EventType.CHANNEL_MSG_RECV, _on_channel_msg)
        client.subscribe(_EventType.CONTACT_MSG_RECV, _on_contact_msg)
        client.subscribe(_EventType.DISCONNECTED, _on_disconnected)
        client.subscribe(_EventType.LOGIN_SUCCESS, _on_login_success)
        client.subscribe(_EventType.LOGIN_FAILED, _on_login_failed)
        client.subscribe(None, _on_any_event)  # log all events at DEBUG level

    async def _fetch_channels(self) -> None:
        channels: list[dict] = []
        for idx in range(8):  # meshcore supports up to 8 configured channels
            result = await self._client.commands.get_channel(idx)
            if result is None or str(result.type) == str(_EventType.ERROR):
                break
            payload = result.payload
            logger.debug("get_channel(%d) payload: %s", idx, payload)
            name = payload.get("channel_name", "").rstrip("\x00").strip()
            if not name:
                name = f"#{idx}"
            key_hex = _extract_channel_key_hex(payload)
            ch: dict = {"idx": idx, "name": name}
            if key_hex:
                ch["key_hex"] = key_hex
            channels.append(ch)
        if not channels:
            channels = [{"idx": 0, "name": "#public"}]
        self._app.post_message(ChannelsUpdated(channels=channels))

    async def _fetch_contacts(self) -> None:
        result = await self._client.commands.get_contacts()
        if hasattr(result, "type") and str(result.type) != str(_EventType.ERROR):
            payload = result.payload
            if isinstance(payload, dict):
                self._contacts = list(payload.values())
            elif isinstance(payload, list):
                self._contacts = payload
            else:
                self._contacts = []
            self._app.post_message(ContactsUpdated(contacts=list(self._contacts)))

    async def disconnect(self) -> None:
        """Disconnect from the companion device."""
        if self._client is None:
            return
        was_connected = self._connected
        try:
            await self._client.stop_auto_message_fetching()
            await self._client.disconnect()
        except Exception:
            pass
        finally:
            self._client = None
            self._connected = False
        if was_connected:
            self._app.post_message(CompanionDisconnected())

    @property
    def contacts(self) -> list[Any]:
        return list(self._contacts)

    @property
    def is_connected(self) -> bool:
        return self._connected

    # --- Outgoing commands (awaited by @work(thread=False) on the widget) ---

    async def send_channel_message(self, channel_idx: int, text: str) -> bool:
        """Send a channel message. Returns True on success."""
        if not self._client or not self._connected:
            return False
        try:
            result = await self._client.commands.send_chan_msg(chan=channel_idx, msg=text)
            return str(getattr(result, "type", "")) != str(_EventType.ERROR)
        except Exception:
            return False

    async def send_repeater_status(self, contact: dict) -> str:
        """Request status from a repeater. Returns response text."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.req_status_sync(contact, min_timeout=3.0)
            if result is None:
                return "timeout"
            return str(result)
        except Exception as exc:
            return f"error: {exc}"

    async def send_repeater_login(self, contact: dict, password: str) -> str:
        """Log in to a repeater. Returns result text."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.send_login(dst=contact, pwd=password)
            return str(result.payload)
        except Exception as exc:
            return f"error: {exc}"

    async def send_contact_cmd(self, contact: dict, cmd: str) -> str:
        """Send a command to any contact. Returns 'sent' on success; response arrives as a contact message."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.send_cmd(dst=contact, cmd=cmd)
            if str(getattr(result, "type", "")) == str(_EventType.ERROR):
                return f"error: {result.payload}"
            return "sent"
        except Exception as exc:
            return f"error: {exc}"

    async def send_repeater_trace(self, contact: dict) -> str:
        """Trace route to a repeater. Returns formatted SNR path or timeout."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            # Determine hash length from the device's path hash mode
            path_hash_mode = await self._client.commands.get_path_hash_mode()
            path_hash_len = path_hash_mode + 1  # bytes per hash element
            if path_hash_len == 3:
                path_hash_len = 2  # firmware only supports 1 or 2
            flags = path_hash_len - 1  # 0→1-byte hashes, 1→2-byte hashes

            out_path = contact.get("out_path", "")
            path_len = contact.get("out_path_len", -1)
            if path_len == -1:
                return "error: no path (flood routing)"

            # Build trace path string (no commas), matching meshcore-cli print_trace_to
            trace = ""
            if contact.get("type") in (2, 3):
                trace = contact.get("public_key", "")[:2 * path_hash_len]
            for i in range(path_len):
                elem = out_path[2 * path_hash_len * (path_len - i - 1):2 * path_hash_len * (path_len - i)]
                trace = elem if trace == "" else f"{elem}{trace}{elem}"

            if not trace:
                return "error: cannot build trace path"

            result = await self._client.commands.send_trace(
                path=bytes.fromhex(trace), flags=flags
            )
            if str(getattr(result, "type", "")) == str(_EventType.ERROR):
                return f"error: {result.payload}"

            tag = int.from_bytes(result.payload.get("expected_ack", b"\x00\x00\x00\x00"), byteorder="little")
            timeout = max(result.payload.get("suggested_timeout", 6000) / 1000 * 1.2, 5.0)
            response = await self._client.dispatcher.wait_for_event(
                _EventType.TRACE_DATA, attribute_filters={"tag": tag}, timeout=timeout
            )
            if response is None:
                return "timeout"
            path_nodes = response.payload.get("path", [])
            if not path_nodes:
                return "no path data"
            parts = []
            for node in path_nodes:
                snr = node.get("snr")
                h = node.get("hash", "")
                snr_str = f"{snr:+.1f}dB" if snr is not None else "?"
                parts.append(f"{h}({snr_str})" if h else f"self({snr_str})")
            return " → ".join(parts)
        except Exception as exc:
            return f"error: {exc}"

    async def send_repeater_reboot(self, contact: dict) -> str:
        """Reboot a repeater."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.send_cmd(dst=contact, cmd="reboot")
            if str(getattr(result, "type", "")) == str(_EventType.ERROR):
                return f"error: {result.payload}"
            return "sent"
        except Exception as exc:
            return f"error: {exc}"

    async def send_contact_msg(self, contact: dict, text: str) -> str:
        """Send a direct message to a contact. Returns result text."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.send_msg_with_retry(dst=contact, msg=text)
            if str(getattr(result, "type", "")) == str(_EventType.ERROR):
                return f"error: {result.payload}"
            return "sent"
        except Exception as exc:
            return f"error: {exc}"

    async def send_contact_ping(self, contact: dict) -> str:
        """Send a path-discovery ping to a contact. Returns path info or timeout."""
        import asyncio as _asyncio
        if not self._client or not self._connected:
            return "not connected"
        try:
            loop = _asyncio.get_event_loop()
            response_future: _asyncio.Future = loop.create_future()

            def _on_path(event: Any) -> None:
                if not response_future.done():
                    response_future.set_result(event)

            pubkey_pre = contact.get("public_key", "")[:12]
            attribute_filters = {"pubkey_pre": pubkey_pre} if pubkey_pre else {}
            sub = self._client.dispatcher.subscribe(
                _EventType.PATH_RESPONSE, _on_path, attribute_filters or None
            )
            try:
                result = await self._client.commands.send_path_discovery(dst=contact)
                if str(getattr(result, "type", "")) == str(_EventType.ERROR):
                    return f"error: {result.payload}"
                timeout = max(result.payload.get("suggested_timeout", 6000) / 600, 5.0)
                try:
                    response = await _asyncio.wait_for(
                        _asyncio.shield(response_future), timeout=timeout
                    )
                    return str(response.payload)
                except _asyncio.TimeoutError:
                    return "timeout"
            finally:
                sub.unsubscribe()
        except Exception as exc:
            return f"error: {exc}"

    async def send_contact_telemetry(self, contact: dict) -> str:
        """Request telemetry from a contact. Returns formatted telemetry string."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.req_telemetry_sync(contact, min_timeout=3.0)
            if result is None:
                return "timeout"
            return str(result)
        except Exception as exc:
            return f"error: {exc}"

    def get_self_info(self) -> dict:
        """Return the current self_info dict from the connected device (no network round-trip)."""
        if not self._client or not self._connected:
            return {}
        return dict(self._client.self_info or {})

    async def send_self_cmd(self, cmd: str) -> str:
        """Handle a local device command typed in the F4 Companion tab.

        Maps text commands to the appropriate meshcore device API calls.
        ``send_cmd`` sends packets over the air to remote contacts and cannot
        be used to address the companion device itself (firmware returns
        ERR_CODE_NOT_FOUND).
        """
        if not self._client or not self._connected:
            return "not connected"

        cmd_lower = cmd.lower().strip()
        try:
            if cmd_lower in ("ver", "version", "infos", "info"):
                return _result_or_error(await self._client.commands.send_appstart())
            elif cmd_lower in ("bat", "battery"):
                return _result_or_error(await self._client.commands.get_bat())
            elif cmd_lower == "time":
                return _result_or_error(await self._client.commands.get_time())
            elif cmd_lower in ("advert", "advertise"):
                return _result_or_error(await self._client.commands.send_advert(), "ok")
            elif cmd_lower in ("device", "devinfo"):
                return _result_or_error(await self._client.commands.send_device_query())
            elif cmd_lower == "reboot":
                return _result_or_error(await self._client.commands.reboot(), "ok")
            elif cmd_lower in ("help", "?"):
                return _SELF_CMD_HELP
            else:
                return f"unknown command '{cmd}' — {_SELF_CMD_HELP}"
        except Exception as exc:
            return f"error: {exc}"

    async def set_channel(
        self, channel_idx: int, channel_name: str, channel_secret: bytes
    ) -> str:
        """Write a channel slot on the companion. Returns 'ok' on success."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.set_channel(
                channel_idx, channel_name, channel_secret
            )
            if str(getattr(result, "type", "")) == str(_EventType.ERROR):
                return f"error: {result.payload}"
            return "ok"
        except Exception as exc:
            return f"error: {exc}"

    async def fetch_channels(self) -> None:
        """Re-fetch channels from the companion and post ChannelsUpdated."""
        if not self._client or not self._connected:
            return
        await self._fetch_channels()
