"""
Regression tests for send_contact_ping, send_contact_telemetry, send_repeater_status.

These tests exist to prevent a specific class of regression that was introduced in
commit ea7a25b ("feat: per-contact logs...") and took down repeater operations:

  1. Ping was simplified by removing the pre-subscribe + pubkey_pre filter → timeouts
  2. Telemetry was switched from req_telemetry_sync (binary 0x32 protocol) back to the
     deprecated send_telemetry_req (0x27) → repeaters don't respond, always timeout
  3. Status was not broken, but was reported as timing out alongside the other two

The assertions here are intentionally protocol-level: they verify *which* meshcore
library call is used, not just what the function returns, so that future refactors
can't silently regress by swapping the underlying call.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from meshcore_tools.companion import CompanionManager


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

CONTACT: dict[str, Any] = {
    "public_key": "aabbccddeeff001122334455",  # 24 hex chars
    "name": "relay1",
    "type": 2,  # repeater
    "out_path": "",
    "out_path_len": -1,
}


def _make_manager() -> CompanionManager:
    """Return a CompanionManager with a connected mock client."""
    mgr = CompanionManager.__new__(CompanionManager)
    mgr._connected = True
    mgr._client = MagicMock()
    mgr._client.commands = MagicMock()
    mgr._client.dispatcher = MagicMock()
    return mgr


def run(coro):
    """Run an async function synchronously — no pytest-asyncio required."""
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# send_contact_ping
# ---------------------------------------------------------------------------


def test_ping_subscribe_called_before_send_path_discovery():
    """
    Subscription must be established BEFORE the discovery packet is sent.

    If the order is reversed (send first, then subscribe) we can miss the
    response on fast links and always time out.  This was the regression in
    ea7a25b that replaced the pre-subscribe pattern with wait_for_event().
    """
    mgr = _make_manager()
    call_order = []
    captured_cb = {}

    def fake_subscribe(event_type, callback, filters=None):
        call_order.append("subscribe")
        captured_cb["fn"] = callback
        sub = MagicMock()
        sub.unsubscribe = MagicMock()
        return sub

    async def fake_send_path_discovery(dst):
        call_order.append("send_path_discovery")
        # Simulate a fast repeater: response arrives before this coroutine returns
        event = MagicMock()
        event.payload = {"path": "aabb"}
        captured_cb["fn"](event)
        return MagicMock(type="MSG_SENT", payload={"suggested_timeout": 3000})

    mgr._client.dispatcher.subscribe.side_effect = fake_subscribe
    mgr._client.commands.send_path_discovery = fake_send_path_discovery

    run(mgr.send_contact_ping(CONTACT))

    assert call_order == ["subscribe", "send_path_discovery"], (
        "dispatcher.subscribe must be called before send_path_discovery; "
        "reversing the order loses PATH_RESPONSE events that arrive before the "
        "subscription is registered (regression: ea7a25b)"
    )


def test_ping_subscribe_uses_pubkey_pre_filter():
    """
    The subscription must filter on pubkey_pre = contact['public_key'][:12].

    Without this filter, PATH_RESPONSE events from *other* contacts on the same
    radio would resolve the future for the wrong contact, producing garbage results
    or unblocking the wrong caller.
    """
    mgr = _make_manager()
    captured_filters = {}

    def fake_subscribe(event_type, callback, filters=None):
        captured_filters.update(filters or {})
        sub = MagicMock()
        sub.unsubscribe = MagicMock()
        return sub

    mgr._client.dispatcher.subscribe.side_effect = fake_subscribe
    mgr._client.commands.send_path_discovery = AsyncMock(return_value=MagicMock(
        type="MSG_SENT",
        payload={"suggested_timeout": 3000},
    ))

    # Patch wait_for to raise immediately — the 5 s floor in send_contact_ping would
    # otherwise make this test wait 5 real seconds (max(3000/600, 5.0) = 5.0).
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        run(mgr.send_contact_ping(CONTACT))

    expected = CONTACT["public_key"][:12]
    assert captured_filters.get("pubkey_pre") == expected, (
        f"pubkey_pre filter must be contact['public_key'][:12] = {expected!r}; "
        "without it, PATH_RESPONSE from other contacts resolves the wrong future"
    )


def test_ping_returns_timeout_when_no_response():
    mgr = _make_manager()
    sub = MagicMock()
    sub.unsubscribe = MagicMock()
    mgr._client.dispatcher.subscribe.return_value = sub
    mgr._client.commands.send_path_discovery = AsyncMock(return_value=MagicMock(
        type="MSG_SENT",
        payload={"suggested_timeout": 3000},
    ))

    # Patch wait_for to raise immediately — the 5 s floor in send_contact_ping would
    # otherwise make this test wait 5 real seconds (max(3000/600, 5.0) = 5.0).
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = run(mgr.send_contact_ping(CONTACT))

    assert result == "timeout"


def test_ping_returns_payload_string_on_success():
    """On a successful ping the payload dict is returned as a string."""
    mgr = _make_manager()
    response_event = MagicMock()
    response_event.payload = {"snr": -10, "path": "ab"}
    captured_cb = {}

    def fake_subscribe(event_type, callback, filters=None):
        captured_cb["fn"] = callback
        sub = MagicMock()
        sub.unsubscribe = MagicMock()
        return sub

    async def fake_send_discovery(dst):
        # Fire the pre-subscribed callback before returning (fast link simulation)
        captured_cb["fn"](response_event)
        return MagicMock(type="MSG_SENT", payload={"suggested_timeout": 3000})

    mgr._client.dispatcher.subscribe.side_effect = fake_subscribe
    mgr._client.commands.send_path_discovery = fake_send_discovery

    result = run(mgr.send_contact_ping(CONTACT))

    assert result == str(response_event.payload)


# ---------------------------------------------------------------------------
# send_contact_telemetry
# ---------------------------------------------------------------------------


def test_telemetry_calls_req_telemetry_sync_not_send_telemetry_req():
    """
    Must call commands.req_telemetry_sync(), NOT commands.send_telemetry_req().

    send_telemetry_req uses the old 0x27 command which modern repeater firmware
    no longer answers — guaranteed timeout.  req_telemetry_sync uses the binary
    0x32 protocol with tag-based response matching, which is reliable.
    Regression introduced in ea7a25b.
    """
    mgr = _make_manager()
    mgr._client.commands.req_telemetry_sync = AsyncMock(return_value=MagicMock())
    mgr._client.commands.send_telemetry_req = AsyncMock()

    run(mgr.send_contact_telemetry(CONTACT))

    mgr._client.commands.req_telemetry_sync.assert_called_once()
    mgr._client.commands.send_telemetry_req.assert_not_called()


def test_telemetry_passes_min_timeout_3():
    """
    min_timeout=3.0 must be passed to req_telemetry_sync.

    Without this floor, short suggested_timeouts from the firmware (e.g. 1 s on
    close nodes) cause premature timeouts for repeaters on slow/long paths.
    """
    mgr = _make_manager()
    mgr._client.commands.req_telemetry_sync = AsyncMock(return_value=MagicMock())

    run(mgr.send_contact_telemetry(CONTACT))

    _, kwargs = mgr._client.commands.req_telemetry_sync.call_args
    assert kwargs.get("min_timeout") == 3.0, (
        "min_timeout=3.0 is required; without it, repeaters on slow paths always timeout"
    )


def test_telemetry_returns_timeout_when_result_is_none():
    mgr = _make_manager()
    mgr._client.commands.req_telemetry_sync = AsyncMock(return_value=None)

    result = run(mgr.send_contact_telemetry(CONTACT))

    assert result == "timeout"


def test_telemetry_returns_str_result_on_success():
    mgr = _make_manager()
    fake_result = MagicMock()
    fake_result.__str__ = lambda self: "batt=4.1V temp=23C"
    mgr._client.commands.req_telemetry_sync = AsyncMock(return_value=fake_result)

    result = run(mgr.send_contact_telemetry(CONTACT))

    assert result == "batt=4.1V temp=23C"


# ---------------------------------------------------------------------------
# send_repeater_status
# ---------------------------------------------------------------------------


def test_status_calls_req_status_sync_not_send_statusreq():
    """
    Must call commands.req_status_sync(), NOT commands.send_statusreq().

    send_statusreq uses the old 0x1b command; repeaters may not return a response
    that can be matched to the request.  req_status_sync uses the binary 0x32
    protocol with tag-based matching — the same mechanism as req_telemetry_sync.
    """
    mgr = _make_manager()
    mgr._client.commands.req_status_sync = AsyncMock(return_value=MagicMock())
    mgr._client.commands.send_statusreq = AsyncMock()

    run(mgr.send_repeater_status(CONTACT))

    mgr._client.commands.req_status_sync.assert_called_once()
    mgr._client.commands.send_statusreq.assert_not_called()


def test_status_passes_min_timeout_3():
    """
    min_timeout=3.0 must be passed to req_status_sync.

    Same rationale as telemetry — short firmware-suggested timeouts would cause
    premature failures for repeaters on multi-hop paths.
    """
    mgr = _make_manager()
    mgr._client.commands.req_status_sync = AsyncMock(return_value=MagicMock())

    run(mgr.send_repeater_status(CONTACT))

    _, kwargs = mgr._client.commands.req_status_sync.call_args
    assert kwargs.get("min_timeout") == 3.0


def test_status_returns_timeout_when_result_is_none():
    mgr = _make_manager()
    mgr._client.commands.req_status_sync = AsyncMock(return_value=None)

    result = run(mgr.send_repeater_status(CONTACT))

    assert result == "timeout"


def test_status_returns_str_result_on_success():
    mgr = _make_manager()
    fake_result = MagicMock()
    fake_result.__str__ = lambda self: "uptime=3600 clients=2"
    mgr._client.commands.req_status_sync = AsyncMock(return_value=fake_result)

    result = run(mgr.send_repeater_status(CONTACT))

    assert result == "uptime=3600 clients=2"
