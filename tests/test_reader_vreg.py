from vedirect_influx.reader import SerialReader


class FakeSerial:
    """Replays one canned HEX response to the next read after a write."""

    def __init__(self, response: bytes):
        self._response, self._armed = response, False

    def reset_input_buffer(self):
        pass

    def write(self, data: bytes):
        self._armed = data.startswith(b":7")

    def read(self, n: int) -> bytes:
        if self._armed:
            self._armed = False
            return self._response
        return b""


def _reader_with(resp: bytes) -> SerialReader:
    r = SerialReader(config=None, sink=None)
    r._ser = FakeSerial(resp)
    return r


def test_vreg_get_returns_status_and_payload():
    # Get(0x0100) -> response register 0x0100, flags 0x00, data 0x75 0xA0
    reader = _reader_with(b":700010075A038\n")
    status, data = reader.vreg_get(0x0100)
    assert status == 0
    assert data == bytes((0x75, 0xA0))


def test_vreg_get_transport_error_on_no_response():
    reader = _reader_with(b"")  # device says nothing
    status, data = reader.vreg_get(0x0100, timeout=0.1, retries=1)
    assert status == 0x8300
    assert data == b""


def test_vreg_get_transport_error_when_port_not_open():
    # IPC GET may arrive before run() opens the port; must not raise.
    reader = SerialReader(config=None, sink=None)  # _ser is None
    assert reader.vreg_get(0x0100) == (0x8300, b"")
