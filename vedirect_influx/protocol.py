"""VE.Direct HEX protocol framing (read-only subset).

Reference: Victron "VE.Direct Protocol" + "BlueSolar-HEX-protocol" PDFs.
Validated against a SmartSolar MPPT 75/15 (PID 0xA075, FW 1.74).
"""

from __future__ import annotations

from dataclasses import dataclass

# Command nibbles (the subset we use; read-only)
CMD_GET = 0x7
CMD_ASYNC = 0xA  # device-initiated; same response shape as Get


def checksum(body: bytes) -> int:
    """Return the HEX frame checksum byte for ``body`` (command byte + payload).

    The frame is valid when ``(sum(command + payload) + checksum) % 256 == 0x55``.

    >>> hex(checksum(bytes((0x07, 0x00, 0x01, 0x00))))  # Get register 0x0100
    '0x4d'
    >>> (sum((0x07, 0x00, 0x01, 0x00)) + checksum(bytes((0x07, 0x00, 0x01, 0x00)))) % 256
    85
    """
    return (0x55 - sum(body)) & 0xFF


def build_get(register: int) -> bytes:
    r"""Build a read-only Get command frame for a 16-bit ``register``.

    The register is encoded little-endian and the command nibble is a single
    char on the wire (``7``).

    >>> build_get(0x0100)        # product id
    b':70001004D\n'
    >>> build_get(0xEDA8)        # documented example
    b':7A8ED00B9\n'
    """
    lo, hi = register & 0xFF, (register >> 8) & 0xFF
    body = bytes((CMD_GET, lo, hi, 0x00))  # cmd, reg LE, flags=0x00
    frame = body + bytes((checksum(body),))
    return b":" + frame.hex().upper().encode()[1:] + b"\n"
    # note: frame.hex() includes the cmd byte as 2 chars "07"; the wire format
    # uses a single nibble "7" for the command, so we drop the leading "0".


@dataclass
class HexResponse:
    """A decoded HEX response frame."""

    command: int
    register: int
    flags: int
    data: bytes  # payload after the flags byte (little-endian fields)
    ok: bool  # flags == 0x00

    @property
    def empty(self) -> bool:
        """Flags 0x04 = register has no data (e.g. empty history slot)."""
        return self.flags == 0x04


def parse_frame(line: bytes) -> HexResponse | None:
    r"""Parse one ``:``-prefixed HEX line into a :class:`HexResponse`.

    Returns ``None`` if the line is not a well-formed Get/Async response or the
    checksum is invalid. Text frames (no leading ``:``) also return ``None``.

    >>> r = parse_frame(b":70001000075A0FF39")   # response to Get 0x0100
    >>> r.register == 0x0100, r.ok
    (True, True)
    >>> parse_frame(b"PID\\t0xA075") is None       # text frame, not HEX
    True
    """
    s = line.strip()
    if not s.startswith(b":"):
        return None
    body_hex = s[1:]
    if len(body_hex) < 1:
        return None
    # command is a single nibble; re-pad to a byte so the rest is byte-aligned
    try:
        raw = bytes.fromhex("0" + body_hex.decode())
    except ValueError:
        return None
    if len(raw) < 5:  # cmd + reg(2) + flags(1) + cksum(1)
        return None
    if checksum(raw[:-1]) != raw[-1]:
        return None
    command = raw[0]
    if command not in (CMD_GET, CMD_ASYNC):
        return None
    register = raw[1] | (raw[2] << 8)
    flags = raw[3]
    data = raw[4:-1]
    return HexResponse(command, register, flags, data, ok=(flags == 0x00))
