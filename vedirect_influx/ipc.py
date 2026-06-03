"""Unix-socket IPC bridging the D-Bus process to the serial-owning reader.

Line protocol: ``GET <reg>`` -> ``OK <status> <hex>``; ``SET`` is rejected
(read-only).
"""

from __future__ import annotations

import logging
import os
import socket
import threading

log = logging.getLogger("vedirect_influx")
DEFAULT_SOCKET = "/run/vedirect-influx/vreg.sock"


class VregIpcServer:
    """Serve VReg reads from ``reader`` over a Unix socket (one thread per conn)."""

    def __init__(self, reader, path: str = DEFAULT_SOCKET) -> None:
        self.reader, self.path = reader, path
        self._sock: socket.socket | None = None
        self._stop = False

    def start(self) -> None:
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.path)
        self._sock.listen(8)
        os.chmod(self.path, 0o660)
        threading.Thread(target=self._serve, daemon=True).start()
        log.info("vreg IPC listening on %s", self.path)

    def _serve(self) -> None:
        assert self._sock is not None  # set in start() before this thread runs
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        with conn, conn.makefile("rwb") as f:
            for raw in f:
                f.write((self._dispatch(raw.decode("ascii", "replace").strip()) + "\n").encode())
                f.flush()

    def _dispatch(self, line: str) -> str:
        parts = line.split()
        if len(parts) == 2 and parts[0] == "GET":
            try:
                reg = int(parts[1], 0)
            except ValueError:
                return "ERR badreg"
            status, data = self.reader.vreg_get(reg)
            return f"OK {status} {data.hex()}"
        if parts and parts[0] == "SET":
            return "ERR readonly"
        return "ERR badcmd"

    def stop(self) -> None:
        self._stop = True
        if self._sock is not None:
            self._sock.close()
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


def vreg_ipc_get(path: str, register: int, timeout: float = 5.0) -> tuple[int, bytes]:
    """Read one register via the IPC socket; return ``(status, data)``."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(path)
        s.sendall(f"GET {register}\n".encode())
        reply = s.makefile("rb").readline().decode("ascii", "replace").strip()
    parts = reply.split()
    if parts and parts[0] == "OK":
        return (int(parts[1]), bytes.fromhex(parts[2]) if len(parts) > 2 else b"")
    raise RuntimeError(f"vreg IPC error: {reply!r}")
