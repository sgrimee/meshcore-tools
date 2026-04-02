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
# Custom Textual messages posted to the app from CompanionManager callbacks
# ---------------------------------------------------------------------------

class CompanionConnected(Message):
    """Posted when the companion device connects and sends self-info."""

    def __init__(self, node_name: str, node_key: str) -> None:
        super().__init__()
        self.node_name = node_name
        self.node_key = node_key


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
                ble_addr = config.ble_name or ""
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
        self._app.post_message(CompanionConnected(node_name=node_name, node_key=node_key))

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

        client.subscribe(_EventType.CHANNEL_MSG_RECV, _on_channel_msg)
        client.subscribe(_EventType.CONTACT_MSG_RECV, _on_contact_msg)
        client.subscribe(_EventType.DISCONNECTED, _on_disconnected)

    async def _fetch_channels(self) -> None:
        channels: list[dict] = []
        for idx in range(8):  # meshcore supports up to 8 configured channels
            result = await self._client.commands.get_channel(idx)
            if result is None or str(result.type) == str(_EventType.ERROR):
                break
            payload = result.payload
            name = payload.get("channel_name", "").rstrip("\x00").strip()
            if not name:
                name = f"#{idx}"
            channels.append({"idx": idx, "name": name})
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
        """Trace route to a repeater."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.send_trace(
                auth_code=0, tag=None, flags=None, path=None
            )
            if str(getattr(result, "type", "")) == str(_EventType.ERROR):
                return f"error: {result.payload}"
            return "sent"
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
            # Pre-subscribe BEFORE sending to avoid missing a fast response
            loop = _asyncio.get_event_loop()
            response_future: _asyncio.Future = loop.create_future()

            def _on_path(event: Any) -> None:
                if not response_future.done():
                    response_future.set_result(event)

            # Filter by the contact's 6-byte pubkey prefix to avoid matching
            # a PATH_RESPONSE from a different contact
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
