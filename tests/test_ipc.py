import socket

from vedirect_influx.ipc import VregIpcServer, vreg_ipc_get


class FakeReader:
    def vreg_get(self, register, timeout=2.0, retries=3):
        return (0, bytes((0x12, 0x34))) if register == 0xED8D else (0x8300, b"")


def test_ipc_get_round_trip(tmp_path):
    sock = str(tmp_path / "vreg.sock")
    server = VregIpcServer(FakeReader(), sock)
    server.start()
    try:
        assert vreg_ipc_get(sock, 0xED8D) == (0, bytes((0x12, 0x34)))
        assert vreg_ipc_get(sock, 0x0001) == (0x8300, b"")
    finally:
        server.stop()


def test_ipc_set_is_rejected(tmp_path):
    sock = str(tmp_path / "vreg.sock")
    server = VregIpcServer(FakeReader(), sock)
    server.start()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(sock)
            s.sendall(b"SET 1 00\n")
            assert s.makefile("rb").readline().strip() == b"ERR readonly"
    finally:
        server.stop()
