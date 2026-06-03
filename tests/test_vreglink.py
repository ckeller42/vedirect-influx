from vedirect_influx.vreglink import SETVREG_READONLY_STATUS, set_response, vreg_response


def test_get_returns_status_and_byte_list():
    calls = {}

    def ipc_get(reg):
        calls["reg"] = reg
        return (0, bytes((0x10, 0x27)))  # 10000 LE

    status, data = vreg_response(ipc_get, 0xED8D)
    assert calls["reg"] == 0xED8D
    assert status == 0
    assert data == bytes((0x10, 0x27))


def test_get_propagates_device_error_status():
    status, data = vreg_response(lambda reg: (0x0100, b""), 0x9999)
    assert status == 0x0100
    assert data == b""


def test_set_is_readonly():
    status, data = set_response(0xED8D, [0x00])
    assert status == SETVREG_READONLY_STATUS
    assert data == b""
