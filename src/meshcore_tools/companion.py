"""CompanionManager — bridges meshcore async client to Textual's event loop.

Import guard: this module imports meshcore at the top level.
Only import it inside `try/except ImportError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.message import Message

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


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------

def _ble_error_message(exc: Exception) -> str:
    """Return a plain-English error message for common BLE/connection failures."""
    msg = str(exc)
    if "NotPermitted" in msg:
        return "BLE: another app is already connected to this device. Disconnect it first."
    if "NotFound" in msg or "DeviceNotFound" in msg:
        return "BLE device not found. Is it turned on and in range?"
    if "NotConnected" in msg:
        return "BLE connection lost. Try again."
    # Strip noisy BlueZ DBus prefix for everything else
    if "org.bluez.Error" in msg:
        return f"BLE error: {msg.split('] ', 1)[-1]}" if '] ' in msg else f"BLE error: {msg}"
    return msg


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
        self._client: object | None = None  # MeshCore instance
        self._contacts: list[dict] = []
        self._connected = False

    async def connect(self, config: ConnectionConfig) -> None:
        """Establish meshcore connection and subscribe to push events."""
        if not _MESHCORE_AVAILABLE:
            self._app.post_message(
                CompanionConnectionError(reason="meshcore package not installed")
            )
            return

        try:
            if config.type == "tcp":
                self._client = await MeshCore.create_tcp(
                    config.host or "127.0.0.1",
                    config.port or 5000,
                )
            elif config.type == "serial":
                self._client = await MeshCore.create_serial(config.device or "")
            elif config.type == "ble":
                self._client = await MeshCore.create_ble(
                    config.ble_name or "", pin=config.ble_pin
                )
            else:
                self._app.post_message(
                    CompanionConnectionError(reason=f"unknown type: {config.type}")
                )
                return
        except Exception as exc:
            self._app.post_message(CompanionConnectionError(reason=_ble_error_message(exc)))
            return

        self._connected = True
        self._subscribe_events()
        await self._fetch_contacts()
        await self._client.start_auto_message_fetching()

        # Notify the app — self-info may arrive asynchronously; send a placeholder
        self._app.post_message(CompanionConnected(node_name="companion", node_key=""))

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
            self._app.post_message(
                ContactMessage(
                    pubkey_prefix=d.get("pubkey_prefix", ""),
                    sender=d.get("sender", d.get("pubkey_prefix", "?")),
                    text=d.get("text", ""),
                    timestamp=int(d.get("timestamp", 0)),
                )
            )

        async def _on_disconnected(event) -> None:
            self._connected = False
            self._app.post_message(CompanionDisconnected())

        client.subscribe(_EventType.CHANNEL_MSG_RECV, _on_channel_msg)
        client.subscribe(_EventType.CONTACT_MSG_RECV, _on_contact_msg)
        client.subscribe(_EventType.DISCONNECTED, _on_disconnected)

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
    def contacts(self) -> list[dict]:
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
            result = await self._client.commands.send_statusreq(dst=contact)
            return str(result.payload)
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

    async def send_repeater_cmd(self, contact: dict, cmd: str) -> str:
        """Send an arbitrary command to a repeater."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.send_cmd(dst=contact, cmd=cmd)
            return str(result.payload)
        except Exception as exc:
            return f"error: {exc}"

    async def send_repeater_trace(self, contact: dict) -> str:
        """Trace route to a repeater."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.send_trace(
                dst=contact, auth_code=0, tag=None, flags=None, path=None
            )
            return str(result.payload)
        except Exception as exc:
            return f"error: {exc}"

    async def send_repeater_reboot(self, contact: dict) -> str:
        """Reboot a repeater."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.send_cmd(dst=contact, cmd="reboot")
            return str(result.payload)
        except Exception as exc:
            return f"error: {exc}"
