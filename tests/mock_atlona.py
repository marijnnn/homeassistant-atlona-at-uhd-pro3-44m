"""Simulated AT-UHD-PRO3-44M Telnet server based on the Atlona API PDF."""
import asyncio
import re


class MockAtlona:
    def __init__(self, *, login=False, user="root", password="Atlona", echo=False,
                 status_has_out5=False, statusx5=True, banner=True, iac=True,
                 split_writes=False, crlf=b"\r\n", fail_status_when_off=False,
                 drop_after=None, silent_pwoff=False, ignore_pwoff=False):
        self.silent_pwoff = silent_pwoff
        self.ignore_pwoff = ignore_pwoff
        self.login = login
        self.user, self.password = user, password
        self.echo = echo
        self.status_has_out5 = status_has_out5
        self.statusx5 = statusx5
        self.banner = banner
        self.iac = iac
        self.split_writes = split_writes
        self.crlf = crlf
        self.fail_status_when_off = fail_status_when_off
        self.drop_after = drop_after  # close connection after N commands
        self.routing = {1: 1, 2: 2, 3: 3, 4: 4, 5: 1}
        self.power = True
        self.enabled = {o: True for o in range(1, 6)}
        self.broadcast = False
        self.received = []
        self.connections = 0
        self.writers = []

    async def start(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        for w in self.writers:
            w.close()
        self.server.close()
        await self.server.wait_closed()

    async def _send(self, writer, data: bytes):
        if self.split_writes:
            for i in range(len(data)):
                writer.write(data[i:i + 1])
                await writer.drain()
                await asyncio.sleep(0.001)
        else:
            writer.write(data)
            await writer.drain()

    async def _readline(self, reader):
        data = await reader.readuntil(b"\r")
        text = data[:-1].decode("latin-1")
        return re.sub("\xff[\xfb-\xfe].", "", text).lstrip("\n")

    async def push_raw(self, data: bytes):
        for w in self.writers:
            w.write(data)
            await w.drain()

    async def push(self, line: str):
        """Simulate broadcast feedback (e.g. a change from the web GUI)."""
        for w in self.writers:
            w.write(line.encode() + self.crlf)
            await w.drain()

    async def _handle(self, reader, writer):
        self.connections += 1
        self.writers.append(writer)
        count = 0
        try:
            if self.iac:
                await self._send(writer, bytes([255, 251, 1, 255, 251, 3]))
            if self.banner:
                await self._send(writer, b"Welcome to TELNET." + self.crlf)
            if self.login:
                await self._send(writer, b"Login: ")
                u = await self._readline(reader)
                await self._send(writer, b"Password: ")
                p = await self._readline(reader)
                if (u, p) != (self.user, self.password):
                    await self._send(writer, b"Login Failed" + self.crlf)
                    writer.close()
                    return
                await self._send(writer, b"Welcome" + self.crlf)
            while True:
                try:
                    cmd = await self._readline(reader)
                except (asyncio.IncompleteReadError, ConnectionError):
                    return
                self.received.append(cmd)
                count += 1
                if self.echo:
                    await self._send(writer, cmd.encode() + self.crlf)
                if cmd == "PWOFF" and (self.silent_pwoff or self.ignore_pwoff):
                    if self.silent_pwoff:
                        self.power = False
                    continue
                reply = self._reply(cmd)
                await self._send(writer, reply.encode() + self.crlf)
                if self.drop_after and count >= self.drop_after:
                    writer.close()
                    return
        except (asyncio.IncompleteReadError, ConnectionError):
            return
        finally:
            if writer in self.writers:
                self.writers.remove(writer)

    def _reply(self, cmd: str) -> str:
        if cmd == "PWSTA":
            return "PWON" if self.power else "PWOFF"
        if cmd in ("PWON", "PWOFF"):
            self.power = cmd == "PWON"
            return cmd
        if cmd == "Status":
            if self.fail_status_when_off and not self.power:
                return f"Command FAILED: ({cmd})"  # format seen on the real device
            outs = range(1, 6) if self.status_has_out5 else range(1, 5)
            return ",".join(f"x{self.routing[o]}AVx{o}" for o in outs)
        if m := re.fullmatch(r"Statusx(\d)", cmd):
            if not self.statusx5:
                return f"Command FAILED: ({cmd})"
            o = int(m.group(1))
            return f"x{self.routing[o]}AVx{o}"
        if m := re.fullmatch(r"x([1-4])AVx([1-5])((?:,x[1-5])*)", cmd):
            i = int(m.group(1))
            for o in [int(m.group(2))] + [int(x) for x in re.findall(r"x(\d)", m.group(3))]:
                self.routing[o] = i
            return cmd
        if m := re.fullmatch(r"x([1-4])All", cmd):
            for o in range(1, 6):
                self.routing[o] = int(m.group(1))
            return cmd
        if m := re.fullmatch(r"x([1-5])\$ (on|off|sta)", cmd):
            o = int(m.group(1))
            if m.group(2) != "sta":
                self.enabled[o] = m.group(2) == "on"
            return f"x{o}$ {'on' if self.enabled[o] else 'off'}"
        if m := re.fullmatch(r"Broadcast (on|off|sta)", cmd):
            if m.group(1) != "sta":
                self.broadcast = m.group(1) == "on"
            return f"Broadcast {'on' if self.broadcast else 'off'}"
        if cmd == "Type":
            return "AT-UHD-PRO3-44M"
        if cmd == "Version":
            return "Firmware 16.1.19"
        return f"Command FAILED: ({cmd})"  # format seen on the real device
