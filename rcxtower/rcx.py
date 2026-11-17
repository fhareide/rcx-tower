"""RCX protocol on top of the USB tower: commands, firmware download, program download."""
import struct
import time

from . import fastdl
from . import tower as tw


class RCXError(Exception):
    pass


class NoReply(RCXError):
    pass


def frame(payload):
    return tw.rcx_frame(payload)


def unframe(raw, expect, length=None):
    """Find a reply whose first byte is `expect`.

    length = number of data bytes after the reply opcode, or None for "whatever
    is there" (only safe once the line has gone quiet). Returns the data bytes
    after the opcode, or None.
    """
    comp = expect ^ 0xFF
    n = len(raw)
    for start in range(n - 1):
        if raw[start] != expect or raw[start + 1] != comp:
            continue
        data = []
        i = start
        while i + 1 < n and raw[i] ^ raw[i + 1] == 0xFF:
            data.append(raw[i])
            i += 2
            if length is not None and len(data) == length + 2:
                break
        if length is not None:
            if len(data) == length + 2 and (sum(data[:-1]) & 0xFF) == data[-1]:
                return bytes(data[1:-1])
        elif len(data) >= 2 and (sum(data[:-1]) & 0xFF) == data[-1]:
            return bytes(data[1:-1])
    return None


def unframe_fast(raw, expect, length):
    """Fast protocol reply: reply opcode, data bytes, one checksum byte; no complements."""
    for start in range(len(raw) - length - 1):
        if raw[start] != expect:
            continue
        body = raw[start:start + 1 + length]
        if (sum(body) & 0xFF) == raw[start + 1 + length]:
            return bytes(body[1:])
    return None


class RCX:
    """Talks to one RCX through a tower.Tower."""

    BYTE_MS = 4.7  # one byte on the IR link at 2400 baud, odd parity

    def __init__(self, tower):
        self.tower = tower
        self._toggle = False
        self._synced = False
        self.fast = False
        try:
            # A fast firmware download that was cut short (here or in another program) leaves
            # the tower at 4800 baud until it is unplugged, and then nothing answers.
            tower.set_speed(tw.SPEED_2400)
        except OSError:
            pass

    # ---- transport -------------------------------------------------------
    def request(self, payload, reply_len=0, retries=4, extra_ms=0, no_reply=False):
        """Send one command and return the reply data (without the reply opcode)."""
        payload = bytes(payload)
        if not self._synced:
            # The RCX treats a command with the same opcode byte as the previous one as a
            # retransmission: it answers but does not act. We cannot know what was sent last
            # (an earlier button press, or BricxCC through the bridge), so start every
            # session with a ping. After that the toggle bit keeps neighbours different.
            self._synced = True
            if payload[0] & 0xF7 != 0x10:
                try:
                    self.request([0x10], 0, retries=2)
                except NoReply:
                    pass
        op = payload[0] ^ (0x08 if self._toggle else 0)
        self._toggle = not self._toggle
        expect = op ^ 0xFF
        if self.fast:
            body = bytes([op]) + payload[1:]
            out = bytes([0xFF]) + body + bytes([sum(body) & 0xFF])
            reply_bytes = 3 + (reply_len or 0)
            byte_ms = self.BYTE_MS / 2
        else:
            out = frame(bytes([op]) + payload[1:])
            reply_bytes = 3 + 2 * ((reply_len or 0) + 2)
            byte_ms = self.BYTE_MS
        budget = (len(out) + reply_bytes) * byte_ms + 350 + extra_ms
        last = b""
        for attempt in range(max(1, retries)):
            if tw.trace:
                tw.trace("cmd %02X (%d data bytes, expecting %s reply bytes, %s, try %d of %d, wait %d ms)" % (
                    payload[0], len(payload) - 1, reply_len, "fast" if self.fast else "normal",
                    attempt + 1, max(1, retries), budget))
            if not self.tower.drain() and tw.trace:
                tw.trace("the receiver is not quiet: something else is sending infrared")
            self.tower.write(out)
            if no_reply:
                time.sleep(len(out) * byte_ms / 1000.0 + 0.05)
                return b""
            buf = bytearray()
            end = time.monotonic() + budget / 1000.0
            while time.monotonic() < end:
                pkt = self.tower.read_packet(30)
                if pkt:
                    buf += pkt
                    if self.fast:
                        got = unframe_fast(buf, expect, reply_len or 0)
                        if got is not None:
                            return got
                    elif reply_len is not None:
                        got = unframe(buf, expect, reply_len)
                        if got is not None:
                            return got
                elif buf and reply_len is None:
                    got = unframe(buf, expect, None)
                    if got is not None:
                        return got
            last = bytes(buf)
            if tw.trace:
                tw.trace("no valid reply to %02X; received %d bytes" % (payload[0], len(last)))
        raise NoReply("no reply to opcode 0x%02X (last bytes: %s)" % (
            payload[0], " ".join("%02X" % b for b in last) or "none"))

    # ---- basic commands --------------------------------------------------
    def ping(self, retries=2):
        try:
            self.request([0x10], 0, retries=retries)
            return True
        except NoReply:
            return False

    def versions(self):
        d = self.request([0x15, 1, 3, 5, 7, 11], 8)
        # four bytes each, e.g. 00 03 02 08 = firmware 3.2.8 (file firm0328)
        rom = "%d.%d" % (d[1], d[2] * 10 + d[3])
        return {"rom": rom, "firmware": "%d.%d.%d" % (d[5], d[6], d[7]),
                "has_firmware": any(d[4:8])}

    def battery_volts(self):
        d = self.request([0x30], 2)
        return (d[0] | d[1] << 8) / 1000.0

    def power_off(self):
        self.request([0x60], 0)

    def play_sound(self, n):
        self.request([0x51, n & 7], 0)

    def play_tone(self, hz, centiseconds):
        self.request([0x23, hz & 0xFF, hz >> 8, centiseconds & 0xFF], 0)

    def select_program(self, slot):
        """slot 1..5"""
        self.request([0x91, (slot - 1) & 0xFF], 0)

    def start_task(self, task=0):
        self.request([0x71, task], 0)

    def stop_all(self):
        self.request([0x50], 0)

    def motors(self, mask, mode):
        """mask: bit0=A bit1=B bit2=C. mode: 'on', 'off' (brake) or 'float'."""
        self.request([0x21, {"on": 0x80, "off": 0x40, "float": 0x00}[mode] | (mask & 7)], 0)

    def motor_direction(self, mask, forward=True):
        self.request([0xE1, (0x80 if forward else 0x00) | (mask & 7)], 0)

    def motor_power(self, mask, level):
        """level 0..7"""
        self.request([0x13, mask & 7, 2, level & 7], 0)

    def value(self, source, arg):
        """Read a value. source 9 = sensor value, 0 = variable, 14 = clock, ..."""
        d = self.request([0x12, source, arg], 2)
        v = d[0] | d[1] << 8
        return v - 0x10000 if v & 0x8000 else v

    # sensor kind: (type code, mode code). Mode 0x00 raw, 0x20 boolean, 0x80 percent,
    # 0xA0 degrees Celsius, 0xE0 rotation steps (16 per turn).
    SENSOR_KINDS = {"raw": (0, 0x00), "touch": (1, 0x20), "temperature": (2, 0xA0),
                    "light": (3, 0x80), "rotation": (4, 0xE0)}

    def set_sensor(self, port, kind):
        """port 1..3, kind one of SENSOR_KINDS. A light sensor's red lamp comes on."""
        stype, mode = self.SENSOR_KINDS[kind]
        self.request([0x32, port - 1, stype], 0)
        self.request([0x42, port - 1, mode], 0)

    def sensor(self, port):
        """Processed value of the sensor on port 1..3 (percent for light, 0/1 for touch...)."""
        return self.value(9, port - 1)

    def sensor_raw(self, port):
        """Raw reading 0..1023 of the sensor on port 1..3."""
        return self.value(12, port - 1)

    def send_message(self, n):
        self.request([0xF7, n & 0xFF], no_reply=True)

    def remote(self, bits):
        """Send a remote-control button mask (same as the LEGO IR remote)."""
        self.request([0xD2, bits & 0xFF, bits >> 8], no_reply=True)

    # ---- bulk transfer ---------------------------------------------------
    def _transfer(self, data, block_size, progress=None, done=0, total=None):
        total = total or len(data)
        count = (len(data) + block_size - 1) // block_size
        for i in range(count):
            chunk = data[i * block_size:(i + 1) * block_size]
            number = 0 if i == count - 1 else i + 1
            cmd = bytes([0x45, number & 0xFF, number >> 8, len(chunk) & 0xFF, len(chunk) >> 8]) \
                + chunk + bytes([sum(chunk) & 0xFF])
            status = self.request(cmd, 1, retries=6)[0]
            if status != 0:
                raise RCXError("RCX rejected data block %d (status %d)" % (i + 1, status))
            done += len(chunk)
            if progress:
                progress(done, total)
        return done

    def set_fast(self, on):
        """Switch tower and framing between the normal and the fast protocol."""
        self.tower.set_speed(tw.SPEED_4800 if on else tw.SPEED_2400)
        self.fast = bool(on)
        self._synced = False

    def download_firmware(self, image, progress=None, fast=False, note=None):
        """image: bytes starting at address 0x8000 (see firmware.load_srec).

        fast: "quad-rate" download. A small stub is sent first at normal speed; it makes
        the RCX talk at 4800 baud without complement bytes. note(text) reports the steps.
        """
        note = note or (lambda text: None)
        if not fast:
            self._send_firmware(image, progress)
        else:
            try:
                if self.ping(retries=3):
                    note("Sending the fast download helper...")
                    self._send_firmware(fastdl.stub(keep_parity=True))
                    time.sleep(0.3)
                else:
                    # an earlier attempt that was cut short leaves the RCX in fast mode
                    note("No answer at normal speed. Trying fast mode...")
                self.set_fast(True)
                if not self.ping(retries=3):
                    raise RCXError("the RCX does not answer in fast mode. Switch it off and on again, "
                                   "then retry (or untick Fast)")
                note("The RCX answers in fast mode. Sending the firmware...")
                self._send_firmware(image, progress)
            finally:
                try:
                    self.set_fast(False)   # the started firmware talks at normal speed again
                except OSError:
                    pass
        time.sleep(0.5)
        v = self.versions()
        if not v["has_firmware"]:
            raise RCXError("firmware was sent but the RCX did not start it (checksum mismatch?)")
        return v

    def _send_firmware(self, image, progress=None):
        start = 0x8000
        check = sum(image[:0x4C00]) & 0xFFFF
        self.request([0x65, 1, 3, 5, 7, 11], 0, extra_ms=500)           # delete old firmware
        self.request([0x75, start & 0xFF, start >> 8, check & 0xFF, check >> 8, 0], 1, extra_ms=500)
        self._transfer(image, 200, progress)
        try:
            self.request(b"\xA5LEGO\xAE", 25, retries=3, extra_ms=3000)  # unlock
        except NoReply:
            # the unlock reply is often lost; the versions check afterwards is what counts
            pass

    def download_program(self, image, slot=None, progress=None):
        """image: bytes of an NQC .rcx file. slot 1..5, or None for the current one."""
        chunks = parse_image(image)
        if slot:
            self.select_program(slot)
        self.stop_all()
        self.request([0x40], 0, extra_ms=300)  # delete all tasks
        self.request([0x70], 0, extra_ms=300)  # delete all subs
        total = sum(len(c[2]) for c in chunks)
        done = 0
        for ctype, number, data in chunks:
            if ctype not in (0, 1):
                continue  # only tasks and subroutines exist on the RCX
            op = 0x25 if ctype == 0 else 0x35
            # five argument bytes: 0, index (16 bit), length (16 bit)
            status = self.request([op, 0, number, 0, len(data) & 0xFF, len(data) >> 8], 1)[0]
            if status == 1:
                raise RCXError("not enough memory on the RCX")
            if status != 0:
                raise RCXError("RCX refused %s %d (status %d)" % ("task" if ctype == 0 else "sub", number, status))
            done = self._transfer(data, 20, progress, done, total)
        self.play_sound(5)
        return len(chunks)


def parse_image(data):
    """Chunks of an NQC .rcx image as (type, number, bytes). type 0 = task, 1 = sub."""
    if data[:4] != b"RCXI":
        raise RCXError("not an NQC .rcx file")
    _version, nchunks, _nsyms, _target, _res = struct.unpack_from("<HHHBB", data, 4)
    off = 12
    chunks = []
    for _ in range(nchunks):
        if off + 4 > len(data):
            raise RCXError("truncated .rcx file")
        ctype, number, length = struct.unpack_from("<BBH", data, off)
        off += 4
        body = data[off:off + length]
        if len(body) != length:
            raise RCXError("truncated .rcx file")
        chunks.append((ctype, number, bytes(body)))
        off += (length + 3) & ~3
    return chunks
