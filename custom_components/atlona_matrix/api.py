"""Async Telnet/TCP client for the Atlona AT-UHD-PRO3-44M.

This module has no Home Assistant dependencies so it can be tested on its own.

Protocol (Atlona API document, firmware 16.1.19):
  * Commands are case-sensitive and terminated with CR (0x0d).
  * Feedback is terminated with CR LF.
  * Most commands answer with an exact copy of the command (e.g. ``x2AVx3``).
  * ``Status``  -> ``x1AVx1,x2AVx2,x3AVx3,x4AVx4`` (output 5 may be missing)
  * ``Statusx5`` -> ``x1AVx5``
  * ``PWSTA``   -> ``PWON`` or ``PWOFF``
  * Errors      -> ``Command FAILED: (<command>)`` (PDF says ``Command FAILED``)
  * With IPLogin enabled (factory default!) the device asks for a username
    and password when the Telnet session starts.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

_LOGGER = logging.getLogger(__name__)

NUM_INPUTS = 4
NUM_OUTPUTS = 5

CONNECT_TIMEOUT = 5.0
RESPONSE_TIMEOUT = 3.0
LOGIN_TIMEOUT = 5.0
INTER_COMMAND_DELAY = 0.05

_ROUTE_TOKEN_RE = re.compile(r"^x(\d+)AVx(\d+)$")
_OUTPUT_TOKEN_RE = re.compile(r"^x(\d+)$")
_ALL_RE = re.compile(r"^x(\d+)All$")
# Output link pulse, verified on the device: '#*PORT1_[\x00]' then ~1.5 s later
# '#*PORT1_[\xff]' when the display on that output re-handshakes (TV on/off,
# but also spontaneously). Not a usable on/off state, kept for diagnostics.
_PORT_RE = re.compile(r"^#\*PORT(\d+)_\[(.)\]$", re.DOTALL)
_ENABLE_RE = re.compile(r"^x(\d+)\$\s*(on|off)$", re.IGNORECASE)
NUM_SWITCHABLE_OUTPUTS = 5  # x?$ works on outputs 1..5 (verified on the device)
_FAILED = "command failed"

# Telnet IAC handling
_IAC, _DONT, _DO, _WONT, _WILL, _SB, _SE = 255, 254, 253, 252, 251, 250, 240


class AtlonaError(Exception):
    """Base error."""


class AtlonaConnectionError(AtlonaError):
    """The device could not be reached or stopped responding."""


class AtlonaNoResponseError(AtlonaConnectionError):
    """Connected, but no valid feedback arrived in time."""


class AtlonaAuthError(AtlonaError):
    """Telnet login was required and failed."""


class AtlonaCommandError(AtlonaError):
    """The device answered ``Command FAILED``."""


@dataclass
class AtlonaState:
    """Last known state of the matrix."""

    routing: dict[int, int | None] = field(
        default_factory=lambda: {o: None for o in range(1, NUM_OUTPUTS + 1)}
    )
    power: bool | None = None
    output_enabled: dict[int, bool | None] = field(
        default_factory=lambda: {o: None for o in range(1, NUM_SWITCHABLE_OUTPUTS + 1)}
    )


def parse_routes(line: str) -> dict[int, int]:
    """Parse routing feedback into {output: input}.

    Handles both ``x1AVx1,x2AVx2`` (Status) and ``x3AVx2,x3,x4``
    (one input to several outputs).
    """
    result: dict[int, int] = {}
    current_input: int | None = None
    for token in line.strip().split(","):
        token = token.strip()
        if m := _ROUTE_TOKEN_RE.match(token):
            current_input = int(m.group(1))
            output = int(m.group(2))
        elif (m := _OUTPUT_TOKEN_RE.match(token)) and current_input is not None:
            output = int(m.group(1))
        else:
            return {}  # not a routing line
        if 1 <= current_input <= NUM_INPUTS and 1 <= output <= NUM_OUTPUTS:
            result[output] = current_input
    return result


def parse_output_enabled(line: str) -> tuple[int, bool] | None:
    """``x2$ on`` -> (2, True)."""
    if m := _ENABLE_RE.match(line.strip()):
        return int(m.group(1)), m.group(2).lower() == "on"
    return None


def parse_power(line: str) -> bool | None:
    line = line.strip()
    if line == "PWON":
        return True
    if line == "PWOFF":
        return False
    return None


class _TelnetFilter:
    """Strips Telnet IAC sequences (also when split across TCP packets).

    Negotiation requests are refused (DO -> WONT, WILL -> DONT) so the
    session stays a plain line-mode connection.
    """

    def __init__(self) -> None:
        self._pending = bytearray()
        self._in_sb = False

    def feed(self, data: bytes) -> tuple[bytes, bytes]:
        """Return (clean data, reply bytes to send back)."""
        buf = self._pending + data
        self._pending = bytearray()
        out = bytearray()
        reply = bytearray()
        i = 0
        n = len(buf)
        while i < n:
            b = buf[i]
            if self._in_sb:
                if b == _IAC and i + 1 < n and buf[i + 1] == _SE:
                    self._in_sb = False
                    i += 2
                elif b == _IAC and i + 1 >= n:
                    self._pending = buf[i:]
                    break
                else:
                    i += 1
                continue
            if b != _IAC:
                out.append(b)
                i += 1
                continue
            if i + 1 >= n:
                self._pending = buf[i:]
                break
            cmd = buf[i + 1]
            if cmd < _SE:
                # Not a Telnet command: the matrix sends raw bytes such as
                # '#*PORT1_[\xff]'. Keep 0xFF as data.
                out.append(b)
                i += 1
                continue
            if cmd == _IAC:
                out.append(_IAC)
                i += 2
            elif cmd in (_DO, _DONT, _WILL, _WONT):
                if i + 2 >= n:
                    self._pending = buf[i:]
                    break
                opt = buf[i + 2]
                if cmd == _DO:
                    reply += bytes((_IAC, _WONT, opt))
                elif cmd == _WILL:
                    reply += bytes((_IAC, _DONT, opt))
                i += 3
            elif cmd == _SB:
                self._in_sb = True
                i += 2
            else:
                i += 2
        return bytes(out), bytes(reply)


class AtlonaClient:
    """Keeps one TCP session to the matrix and serialises commands."""

    def __init__(
        self,
        host: str,
        port: int = 23,
        username: str | None = None,
        password: str | None = None,
        *,
        response_timeout: float = RESPONSE_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username or None
        self.password = password or ""
        self.response_timeout = response_timeout
        self.state = AtlonaState()
        self.supports_statusx5: bool | None = None
        self.on_unsolicited: Callable[[], None] | None = None
        self.on_connection_lost: Callable[[], None] | None = None

        # Last TX/RX lines, for the diagnostics download.
        self.history: collections.deque[tuple[str, str, str]] = collections.deque(maxlen=100)
        self.connect_count = 0
        # output -> {"pulses": n, "last": iso time, "value": last byte}
        self.port_events: dict[int, dict] = {}
        self.last_error: str | None = None

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None
        self._pending: tuple[str, Callable[[str], bool], asyncio.Future] | None = None
        self._lock = asyncio.Lock()
        self._filter = _TelnetFilter()
        self._buffer = ""
        self._lines: list[str] = []

    # ------------------------------------------------------------------ I/O

    @property
    def connected(self) -> bool:
        return (
            self._writer is not None
            and not self._writer.is_closing()
            and self._reader_task is not None
            and not self._reader_task.done()
        )

    def _log(self, direction: str, text: str) -> None:
        self.history.append(
            (datetime.now(timezone.utc).isoformat(timespec="milliseconds"), direction, text)
        )

    def _fail_pending(self, err: Exception) -> None:
        if self._pending and not self._pending[2].done():
            self._pending[2].set_exception(err)

    async def close(self) -> None:
        task = self._reader_task
        self._reader_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._fail_pending(AtlonaConnectionError("Connection closed"))
        writer = self._writer
        self._reader = None
        self._writer = None
        self._buffer = ""
        self._lines = []
        self._filter = _TelnetFilter()
        if writer is not None:
            try:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), timeout=2)
            except (OSError, asyncio.TimeoutError):
                pass

    async def _read_chunk(self, timeout: float) -> bool:
        """Read one chunk into the line buffer. Returns False on timeout."""
        assert self._reader is not None
        try:
            data = await asyncio.wait_for(self._reader.read(4096), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        if not data:
            raise AtlonaConnectionError("Connection closed by Atlona")
        clean, reply = self._filter.feed(data)
        if reply and self._writer is not None:
            self._writer.write(reply)
        text = clean.decode("latin-1")  # keep raw bytes (e.g. 0x00/0xFF in #*PORT messages)
        _LOGGER.debug("RX %r", text)
        self._buffer += text
        parts = re.split(r"\r\n|\r|\n", self._buffer)
        self._buffer = parts.pop()  # incomplete tail
        self._lines.extend(p.strip() for p in parts if p.strip())
        return True

    def _peek_prompt(self) -> str:
        """Incomplete (un-terminated) text, e.g. a ``Login:`` prompt."""
        return self._buffer.strip()

    async def _write(self, text: str) -> None:
        assert self._writer is not None
        _LOGGER.debug("TX %r", text)
        self._log("TX", text)
        self._writer.write(text.encode("ascii") + b"\r")
        await self._writer.drain()

    async def _connect(self) -> None:
        await self.close()
        _LOGGER.debug("Connecting to %s:%s", self.host, self.port)
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=CONNECT_TIMEOUT
            )
        except (OSError, asyncio.TimeoutError) as err:
            await self.close()
            raise AtlonaConnectionError(
                f"Cannot connect to {self.host}:{self.port}: {err}"
            ) from err
        try:
            await self._handle_banner_and_login()
            self.connect_count += 1
            self._reader_task = asyncio.get_running_loop().create_task(
                self._reader_loop(), name="atlona_reader"
            )
        except AtlonaError:
            await self.close()
            raise
        except OSError as err:
            await self.close()
            raise AtlonaConnectionError(str(err)) from err

    async def _handle_banner_and_login(self) -> None:
        """Consume the welcome banner and log in if the device asks for it."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + LOGIN_TIMEOUT
        sent_user = sent_pass = False
        quiet_since = loop.time()
        while loop.time() < deadline:
            got = await self._read_chunk(0.3)
            seen = " ".join(self._lines + [self._peek_prompt()]).lower()
            if got:
                quiet_since = loop.time()
            if sent_pass and re.search(
                r"(fail|invalid|incorrect|denied|error|login\s*:?\s*$|password\s*:?\s*$)", seen
            ):
                raise AtlonaAuthError("Atlona rejected the Telnet username/password")
            if not sent_user and re.search(r"(login|user ?name)\s*:?\s*$", seen):
                if not self.username:
                    raise AtlonaAuthError(
                        "Atlona asks for a Telnet login: enter username/password "
                        "or disable it on the device with 'IPLogin off'"
                    )
                self._lines.clear()
                self._buffer = ""
                await self._write(self.username)
                sent_user = True
                continue
            if re.search(r"password\s*:?\s*$", seen):
                if not self.username:
                    raise AtlonaAuthError("Atlona asks for a Telnet password")
                self._lines.clear()
                self._buffer = ""
                await self._write(self.password)
                sent_pass = True
                quiet_since = loop.time()
                continue
            # Nothing new for a short while -> banner/login finished.
            if loop.time() - quiet_since > (0.6 if sent_pass else 0.4):
                break
        if self._lines or self._buffer:
            _LOGGER.debug("Discarding connect banner: %r", self._lines + [self._buffer])
        self._lines.clear()
        self._buffer = ""

    async def _reader_loop(self) -> None:
        """Owns the socket while connected: answers requests, handles pushes."""
        try:
            while True:
                await self._read_chunk(3600)
                self._dispatch_lines()
        except asyncio.CancelledError:
            raise
        except (AtlonaError, OSError) as err:
            _LOGGER.debug("Atlona connection lost: %s", err)
            self.last_error = str(err)
            self._fail_pending(AtlonaConnectionError(str(err)))
            writer, self._writer, self._reader = self._writer, None, None
            if writer is not None:
                writer.close()
            if self.on_connection_lost:
                try:
                    self.on_connection_lost()
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Error in Atlona connection-lost callback")

    def _dispatch_lines(self) -> None:
        changed = False
        while self._lines:
            line = self._lines.pop(0)
            self._log("RX", line)
            pending = self._pending
            if pending and not pending[2].done():
                command, matcher, future = pending
                if line.lower().startswith(_FAILED):  # "Command FAILED: (xyz)"
                    future.set_exception(
                        AtlonaCommandError(f"Atlona answered {line!r} to {command}")
                    )
                    continue
                if matcher(line):
                    future.set_result(line)
                    continue
                if line == command:  # plain Telnet echo
                    continue
            # Not an answer to our request: broadcast / unsolicited feedback.
            if self._apply_feedback(line):
                changed = True
                _LOGGER.debug("Unsolicited Atlona feedback: %r", line)
        if changed and self.on_unsolicited:
            try:
                self.on_unsolicited()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error in Atlona update callback")

    def _apply_feedback(self, line: str) -> bool:
        if routes := parse_routes(line):
            self.state.routing.update(routes)
            return True
        if (m := _ALL_RE.match(line)) and 1 <= int(m.group(1)) <= NUM_INPUTS:
            for out in range(1, NUM_OUTPUTS + 1):
                self.state.routing[out] = int(m.group(1))
            return True
        if (power := parse_power(line)) is not None:
            self.state.power = power
            return True
        if m := _PORT_RE.match(line):
            port = int(m.group(1))
            ev = self.port_events.setdefault(port, {"pulses": 0, "last": None, "value": None})
            ev["value"] = ord(m.group(2))
            if ev["value"] == 0:
                ev["pulses"] += 1
                ev["last"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            return False  # informational only
        if (enabled := parse_output_enabled(line)) and enabled[0] in self.state.output_enabled:
            self.state.output_enabled[enabled[0]] = enabled[1]
            return True
        return False

    async def _exchange(
        self, command: str, matcher: Callable[[str], bool], timeout: float | None = None
    ) -> str:
        """Send ``command`` and return the first line accepted by ``matcher``."""
        if not self.connected:
            await self._connect()
        timeout = timeout or self.response_timeout
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending = (command, matcher, future)
        try:
            await self._write(command)
            try:
                line = await asyncio.wait_for(asyncio.shield(future), timeout)
            except asyncio.TimeoutError:
                raise AtlonaNoResponseError(
                    f"No valid response to {command!r} within {timeout}s"
                ) from None
        finally:
            self._pending = None
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()  # mark retrieved
        await asyncio.sleep(INTER_COMMAND_DELAY)
        return line

    async def _request(
        self,
        command: str,
        matcher: Callable[[str], bool],
        *,
        retry: bool = True,
        timeout: float | None = None,
    ) -> str:
        """Exchange with one automatic reconnect on connection problems."""
        async with self._lock:
            for attempt in (1, 2):
                try:
                    return await self._exchange(command, matcher, timeout)
                except AtlonaConnectionError as err:
                    self.last_error = str(err)
                    await self.close()
                    if attempt == 2 or not retry:
                        raise
                    _LOGGER.debug("Retrying %s after error: %s", command, err)
                except OSError as err:
                    self.last_error = str(err)
                    await self.close()
                    if attempt == 2 or not retry:
                        raise AtlonaConnectionError(str(err)) from err
                except AtlonaError:
                    raise  # e.g. Command FAILED: not a connection problem
            raise AtlonaConnectionError("unreachable")  # pragma: no cover

    # ------------------------------------------------------------ commands

    async def send_echo_command(self, command: str) -> None:
        """Send a command whose feedback is the command itself."""
        await self._request(command, lambda line: line == command)

    async def route(self, input_no: int, output_no: int) -> None:
        _check(input_no, NUM_INPUTS, "input")
        _check(output_no, NUM_OUTPUTS, "output")
        await self.send_echo_command(f"x{input_no}AVx{output_no}")
        self.state.routing[output_no] = input_no

    async def route_all(self, input_no: int) -> None:
        _check(input_no, NUM_INPUTS, "input")
        await self.send_echo_command(f"x{input_no}All")
        for out in range(1, NUM_OUTPUTS + 1):
            self.state.routing[out] = input_no

    async def set_power(self, on: bool) -> None:
        command = "PWON" if on else "PWOFF"
        try:
            # Not retried: never send PWON/PWOFF twice.
            await self._request(command, lambda line: line == command, retry=False, timeout=2.0)
        except AtlonaNoResponseError:
            # Observed on the real device: PWOFF sometimes gives no feedback at
            # all although it is executed. Verify with PWSTA instead.
            _LOGGER.debug("No feedback for %s, verifying with PWSTA", command)
            await asyncio.sleep(0.5)
            if await self.get_power() != on:
                raise AtlonaCommandError(f"{command} was not executed (PWSTA disagrees)")
        self.state.power = on

    async def get_power(self) -> bool:
        line = await self._request("PWSTA", lambda l: parse_power(l) is not None)
        self.state.power = parse_power(line)
        return bool(self.state.power)

    async def get_routing(self) -> dict[int, int | None]:
        line = await self._request("Status", lambda l: bool(parse_routes(l)))
        self.state.routing.update(parse_routes(line))
        if NUM_OUTPUTS not in parse_routes(line) and self.supports_statusx5 is not False:
            # Output 5 (HDMI) is not always part of the Status answer.
            try:
                line5 = await self._request(
                    f"Statusx{NUM_OUTPUTS}",
                    lambda l: NUM_OUTPUTS in parse_routes(l),
                )
            except AtlonaCommandError:
                _LOGGER.debug("Statusx%s not supported; output %s state unknown",
                              NUM_OUTPUTS, NUM_OUTPUTS)
                self.supports_statusx5 = False
            else:
                self.supports_statusx5 = True
                self.state.routing.update(parse_routes(line5))
        return dict(self.state.routing)

    async def set_output_enabled(self, output_no: int, enabled: bool) -> None:
        """Enable/disable (blank) an HDBaseT output: ``x2$ on`` / ``x2$ off``."""
        _check(output_no, NUM_SWITCHABLE_OUTPUTS, "output")
        command = f"x{output_no}$ {'on' if enabled else 'off'}"
        await self._request(
            command,
            lambda l: parse_output_enabled(l) == (output_no, enabled),
        )
        self.state.output_enabled[output_no] = enabled

    async def get_output_enabled(self, output_no: int) -> bool:
        _check(output_no, NUM_SWITCHABLE_OUTPUTS, "output")
        line = await self._request(
            f"x{output_no}$ sta",
            lambda l: (r := parse_output_enabled(l)) is not None and r[0] == output_no,
        )
        enabled = parse_output_enabled(line)[1]
        self.state.output_enabled[output_no] = enabled
        return enabled

    async def set_broadcast(self, enabled: bool) -> None:
        """Let the matrix push changes (web GUI etc.) to this session."""
        command = f"Broadcast {'on' if enabled else 'off'}"
        await self._request(command, lambda l: l.lower() == command.lower())

    async def get_text(self, command: str) -> str:
        """For informational commands like ``Type`` or ``Version``."""
        return await self._request(command, lambda line: line != command)


def _check(value: int, maximum: int, what: str) -> None:
    if not 1 <= value <= maximum:
        raise ValueError(f"{what} must be 1..{maximum}, got {value}")
