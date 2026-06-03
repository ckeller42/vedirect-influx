"""Pure VregLink request logic (no D-Bus).

``GetVreg`` proxies a register read to the serial reader; ``SetVreg`` is
read-only by design.
"""

from __future__ import annotations

from collections.abc import Callable

#: VReg result code returned for any write attempt: 0x8102 = "VREG is read-only".
SETVREG_READONLY_STATUS = 0x8102


def vreg_response(ipc_get: Callable[[int], tuple[int, bytes]], register: int) -> tuple[int, bytes]:
    """Return ``(status, data)`` for a GetVreg, delegating the read to ``ipc_get``."""
    return ipc_get(register)


def set_response(register: int, data: list[int]) -> tuple[int, bytes]:
    """Reject writes: return the read-only status with empty data."""
    return (SETVREG_READONLY_STATUS, b"")
