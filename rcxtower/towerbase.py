"""What every tower backend shares: the tower's USB requests, errors, and RCX packet framing."""
import time

VENDOR_ID = 0x0694
PRODUCT_ID = 0x0001

# Vendor requests understood by the tower firmware
REQ_GET_PARM = 0x01
REQ_SET_PARM = 0x02
REQ_FLUSH = 0x03
REQ_RESET = 0x04
REQ_GET_STAT = 0x05
REQ_GET_POWER = 0x06
REQ_GET_TX_SPEED = 0xEE
REQ_SET_TX_SPEED = 0xEF
REQ_GET_RX_SPEED = 0xF0
REQ_SET_RX_SPEED = 0xF1
REQ_GET_CAPS = 0xFC
REQ_GET_VERSION = 0xFD
REQ_GET_COPYRIGHT = 0xFE

SPEED_2400 = 0x0008   # values for REQ_SET_TX_SPEED / REQ_SET_RX_SPEED
SPEED_4800 = 0x0010

PARM_MODE = 0x01      # 1 = VLL, 2 = IR, 4 = IRC, 8 = radio
PARM_RANGE = 0x02     # 1 = short, 2 = medium, 3 = long
RANGE_SHORT, RANGE_MEDIUM, RANGE_LONG = 1, 2, 3

EP_IN = 0x81   # interrupt endpoint: IR bytes received
EP_OUT = 0x02  # interrupt endpoint: IR bytes to send


class TowerError(OSError):
    pass


class TowerBase:
    """A backend provides control(), write(), read_packet() and close()."""

    packet_size = 8

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def set_parm(self, parm, value):
        return self.control(REQ_SET_PARM, parm | (value << 8))

    def get_parm(self, parm):
        return self.control(REQ_GET_PARM, parm)

    def reset(self):
        return self.control(REQ_RESET)

    def set_speed(self, speed):
        """IR speed, SPEED_2400 (normal) or SPEED_4800. The transmit speed has to be set first.
        The tower keeps the speed for as long as it is plugged in."""
        self.control(REQ_SET_TX_SPEED, speed)
        self.control(REQ_SET_RX_SPEED, speed)

    def read(self, total_ms=500, quiet_ms=80):
        """Collect bytes until the line has been quiet for quiet_ms or total_ms passed."""
        out = bytearray()
        end = time.monotonic() + total_ms / 1000.0
        while time.monotonic() < end:
            got = self.read_packet(quiet_ms)
            if got:
                out += got
            elif out:
                break
        return bytes(out)

    def drain(self, limit_ms=400):
        """Throw away what is waiting. Gives up after limit_ms: if something keeps sending
        (another tower, a remote control, sunlight on the receiver) this must not wait forever."""
        end = time.monotonic() + limit_ms / 1000.0
        while self.read_packet(20):
            if time.monotonic() > end:
                return False
        return True


def rcx_frame(payload):
    """Wrap RCX opcode+args in the IR framing: header, byte/complement pairs, checksum."""
    out = bytearray(b"\x55\xff\x00")
    total = 0
    for b in payload:
        out += bytes((b, b ^ 0xFF))
        total += b
    total &= 0xFF
    out += bytes((total, total ^ 0xFF))
    return bytes(out)
