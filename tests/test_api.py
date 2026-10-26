"""Protocol tests for api.py against a simulated AT-UHD-PRO3-44M (no Home Assistant needed)."""
import asyncio
import time

import pytest

from custom_components.atlona_matrix import api

from .mock_atlona import MockAtlona


async def _with(mock_kwargs, fn, **client_kwargs):
    mock = await MockAtlona(**mock_kwargs).start()
    client = api.AtlonaClient("127.0.0.1", mock.port, **client_kwargs)
    try:
        return await fn(client, mock)
    finally:
        await client.close()
        await mock.stop()


async def test_parse_routes(socket_enabled):
    assert api.parse_routes("x1AVx1,x2AVx2,x3AVx3,x4AVx4") == {1: 1, 2: 2, 3: 3, 4: 4}
    assert api.parse_routes("x3AVx2,x3,x4") == {2: 3, 3: 3, 4: 3}
    assert api.parse_routes("x1AVx5") == {5: 1}
    assert api.parse_routes("Status") == {}
    assert api.parse_routes("PWON") == {}


@pytest.mark.parametrize("kw", [
    {},
    {"echo": True},
    {"split_writes": True},
    {"crlf": b"\r"},
    {"crlf": b"\n\r"},
    {"iac": False, "banner": False},
    {"status_has_out5": True},
])
async def test_poll_and_route(kw, socket_enabled):
    async def fn(c, m):
        routing = await c.get_routing()
        assert routing == {1: 1, 2: 2, 3: 3, 4: 4, 5: 1}
        assert await c.get_power() is True
        await c.route(3, 2)
        assert m.routing[2] == 3 and c.state.routing[2] == 3
        await c.route(2, 5)
        assert m.routing[5] == 2
        await c.route_all(4)
        assert set(m.routing.values()) == {4}
        await c.set_power(False)
        assert await c.get_power() is False
        assert (await c.get_routing())[5] == 4
        assert m.connections == 1, "should reuse a single TCP session"
        assert "PWSTA" in m.received
    await (_with(kw, fn))


async def test_statusx5_not_supported(socket_enabled):
    async def fn(c, m):
        r = await c.get_routing()
        assert r[5] is None and r[1] == 1
        assert c.supports_statusx5 is False
        await c.get_routing()
        assert m.received.count("Statusx5") == 1  # not retried every poll
    await (_with({"statusx5": False}, fn))


async def test_login_ok(socket_enabled):
    async def fn(c, m):
        assert (await c.get_routing())[3] == 3
    await (_with({"login": True}, fn, username="root", password="Atlona"))


async def test_login_missing_credentials(socket_enabled):
    async def fn(c, m):
        with pytest.raises(api.AtlonaAuthError):
            await c.get_power()
    await (_with({"login": True}, fn))


async def test_login_wrong_password(socket_enabled):
    async def fn(c, m):
        with pytest.raises(api.AtlonaAuthError):
            await c.get_power()
    await (_with({"login": True}, fn, username="root", password="nope"))


async def test_reconnect_after_device_closes(socket_enabled):
    async def fn(c, m):
        for _ in range(5):
            assert await c.get_power() is True
        assert m.connections >= 2
    await (_with({"drop_after": 2}, fn))


async def test_command_failed(socket_enabled):
    async def fn(c, m):
        await c.set_power(False)
        with pytest.raises(api.AtlonaCommandError):
            await c.get_routing()
        # session must still be usable afterwards
        assert await c.get_power() is False
    await (_with({"fail_status_when_off": True}, fn))


async def test_unsolicited_broadcast_updates_state(socket_enabled):
    async def fn(c, m):
        calls = []
        c.on_unsolicited = lambda: calls.append(1)
        await c.get_power()
        await m.push("x2AVx1,x3,x4")
        await asyncio.sleep(0.05)
        await c.get_power()
        assert c.state.routing[1] == 2 and c.state.routing[4] == 2
        assert calls
    await (_with({}, fn))


async def test_unreachable(socket_enabled):
    async def fn():
        c = api.AtlonaClient("127.0.0.1", 1)
        with pytest.raises(api.AtlonaConnectionError):
            await c.get_power()
    await (fn())


async def test_no_answer_times_out(socket_enabled):
    async def fn():
        async def silent(r, w):
            await asyncio.sleep(10)
        srv = await asyncio.start_server(silent, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        c = api.AtlonaClient("127.0.0.1", port, response_timeout=0.5)
        with pytest.raises(api.AtlonaConnectionError):
            await c.get_power()
        await c.close()
        srv.close()
    await (fn())


async def test_concurrent_commands_serialised(socket_enabled):
    async def fn(c, m):
        await asyncio.gather(*(c.route(i % 4 + 1, i % 5 + 1) for i in range(10)),
                             c.get_routing(), c.get_power())
        assert m.connections == 1
    await (_with({"split_writes": True}, fn))


async def test_info_commands(socket_enabled):
    async def fn(c, m):
        assert await c.get_text("Version") == "Firmware 16.1.19"
        assert await c.get_text("Type") == "AT-UHD-PRO3-44M"
    await (_with({"echo": True}, fn))


async def test_real_device_status_sample(socket_enabled):
    assert api.parse_routes("x1AVx1,x2AVx2,x1AVx3,x1AVx4,x1AVx5") == {1: 1, 2: 2, 3: 1, 4: 1, 5: 1}
    async def fn(c, m):
        m.routing = {1: 1, 2: 2, 3: 1, 4: 1, 5: 1}
        assert await c.get_routing() == {1: 1, 2: 2, 3: 1, 4: 1, 5: 1}
        assert "Statusx5" not in m.received
    await (_with({"status_has_out5": True}, fn))


async def test_pwoff_without_feedback_is_verified(socket_enabled):
    async def fn(c, m):
        await c.get_power()
        await c.set_power(False)
        assert c.state.power is False and m.power is False
        assert m.received.count("PWOFF") == 1, "PWOFF must not be sent twice"
        # polling keeps working afterwards
        assert (await c.get_routing())[1] == 1
    await (_with({"silent_pwoff": True}, fn))


async def test_pwoff_ignored_raises(socket_enabled):
    async def fn(c, m):
        with pytest.raises(api.AtlonaCommandError):
            await c.set_power(False)
        assert await c.get_power() is True
    await (_with({"ignore_pwoff": True}, fn))


async def test_real_failed_format_is_fast(socket_enabled):
    async def fn(c, m):
        t = time.monotonic()
        with pytest.raises(api.AtlonaCommandError):
            await c.get_text("BogusCmd")
        assert time.monotonic() - t < 1.0
        assert m.received.count("BogusCmd") == 1
    await (_with({}, fn))


async def test_output_enable(socket_enabled):
    async def fn(c, m):
        assert await c.get_output_enabled(5) is True
        await c.set_output_enabled(2, False)
        assert m.enabled[2] is False and c.state.output_enabled[2] is False
        assert await c.get_output_enabled(2) is False
        await c.set_output_enabled(2, True)
        assert m.enabled[2] is True
    await (_with({}, fn))


async def test_push_between_polls_with_real_device_noise(socket_enabled):
    """Broadcast pushes arrive while idle; real device also sends '#*PORT1_[\\xff]'."""
    async def fn(c, m):
        calls = []
        c.on_unsolicited = lambda: calls.append(1)
        await c.set_broadcast(True)
        assert m.broadcast
        await m.push_raw(b"#*PORT1_[\x00]\r\n#*PORT1_[\xff]\r\n")
        await m.push("x1AVx2")
        await asyncio.sleep(0.1)  # no command sent: reader task must handle it
        assert c.state.routing[2] == 1 and len(calls) == 1
        await m.push("x3AVx5")
        await asyncio.sleep(0.1)
        assert c.state.routing[5] == 3 and len(calls) == 2
        # normal commands still work after the noise
        assert await c.get_power() is True
        assert c.history and c.history[-1][1] == "RX"
    await (_with({}, fn))


async def test_reader_detects_drop_and_reconnects(socket_enabled):
    async def fn(c, m):
        await c.get_power()
        for w in list(m.writers):
            w.close()
        await asyncio.sleep(0.1)
        assert not c.connected
        assert await c.get_power() is True
        assert c.connect_count == 2
    await (_with({}, fn))
