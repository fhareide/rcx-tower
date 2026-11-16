"""Read RCX firmware files (.lgo / .srec, Motorola S-records)."""


import os

BUNDLED_NAME = "firm0328.lgo"  # LEGO RCX 2.0 firmware 3.2.8, from the LEGO Mindstorms SDK 2.5


class FirmwareError(Exception):
    pass


def bundled_path():
    """Path of the firmware shipped with this program, or None if it was left out."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", BUNDLED_NAME)
    return path if os.path.isfile(path) else None


def load_srec(path, base=0x8000):
    """Return the firmware image as bytes starting at `base`."""
    image = bytearray()
    records = 0
    with open(path, "r", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line[0] != "S":
                continue
            kind = line[1]
            addr_len = {"1": 2, "2": 3, "3": 4}.get(kind)
            if addr_len is None:
                continue  # header, count and start-address records
            try:
                raw = bytes.fromhex(line[2:])
            except ValueError:
                raise FirmwareError("line %d is not valid hex" % lineno)
            if not raw or raw[0] != len(raw) - 1:
                raise FirmwareError("line %d has a wrong length" % lineno)
            if (sum(raw) & 0xFF) != 0xFF:
                raise FirmwareError("line %d has a bad checksum" % lineno)
            addr = int.from_bytes(raw[1:1 + addr_len], "big")
            data = raw[1 + addr_len:-1]
            if addr < base:
                raise FirmwareError("line %d is below address 0x%04X" % (lineno, base))
            end = addr - base + len(data)
            if end > 0x8000:
                raise FirmwareError("line %d is beyond the RCX memory" % lineno)
            if end > len(image):
                image.extend(b"\0" * (end - len(image)))
            image[addr - base:end] = data
            records += 1
    if not records:
        raise FirmwareError("no firmware data found in %s" % path)
    return bytes(image)
