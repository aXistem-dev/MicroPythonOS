# Request/response link to the SenseCAP Indicator's RP2040 over the inter-board UART
# (interdevice.proto frames, see proto.py). One request is on the wire at a time: callers on
# different threads (the UI reading files, the audio thread playing a tune, an app talking to a
# Grove sensor) take turns on a lock, and each reply is matched to its request by id.

import errno
import logging
import time

import _thread

from . import proto

logger = logging.getLogger(__name__)

MAX_PAYLOAD = 4700          # largest legal InterdeviceMessage is 4666 bytes (a 4 KB file chunk)
STALL_MS = 30               # a whole frame takes ~23 ms at 2 Mbaud: a frame still incomplete after
                            # this long with no new bytes had a false or damaged header


class LinkError(OSError):
    pass


class LinkTimeout(LinkError):
    def __init__(self, what="no reply from the RP2040"):
        super().__init__(errno.ETIMEDOUT, what)


class LinkNack(LinkError):
    """The RP2040 could not decode the request or does not handle that kind of request."""

    def __init__(self, what="RP2040 refused the request"):
        super().__init__(errno.EIO, what)


class LinkVersionError(LinkError):
    def __init__(self, version):
        super().__init__(errno.ENODEV, "RP2040 speaks interdevice version %d" % version)
        self.version = version


class Link:
    """`uart` needs write(bytes), any() and read(n) (machine.UART with timeout=0)."""

    def __init__(self, uart, timeout_ms=500):
        self.uart = uart
        self.timeout_ms = timeout_ms
        self.hellos = 0              # unsolicited pings: the RP2040 (re)started
        self.on_nmea = None          # callable(sentence) for a GPS on the RP2040's serial port
        self._lock = _thread.allocate_lock()
        self._buf = b""             # received, not yet framed (bytes: MicroPython bytearrays
        self._next_id = 1           # cannot delete slices)
        self._available = False
        self._last_rx = time.ticks_ms()
        self._inbox = []            # unsolicited messages, handled once the lock is released

    # --- public ---------------------------------------------------------- #
    def connect(self, raise_errors=True):
        """Ping and check the protocol version. Returns True when the RP2040 answers with the
        version this driver speaks; otherwise the link stays unavailable."""
        try:
            version = self.ping()
            if version != proto.INTERDEVICE_VERSION:
                raise LinkVersionError(version)
        except LinkError:
            self._available = False
            if raise_errors:
                raise
            return False
        self._available = True
        return True

    def available(self):
        return self._available

    def ping(self):
        """The peer's protocol version. A reply in our version marks the link available."""
        version = self.request({"ping": proto.INTERDEVICE_VERSION})["pong"]
        if version == proto.INTERDEVICE_VERSION:
            self._available = True
        return version

    def request(self, msg, timeout_ms=None):
        """Send `msg` (an InterdeviceMessage dict without id) and return the reply."""
        try:
            with self._lock:
                rid = self._take_id()
                out = dict(msg)
                out["id"] = rid
                self.uart.write(proto.frame(proto.encode(out)))
                limit = self.timeout_ms if timeout_ms is None else timeout_ms
                t0 = time.ticks_ms()
                while True:
                    reply = self._next_frame()
                    if reply is None:
                        if time.ticks_diff(time.ticks_ms(), t0) > limit:
                            raise LinkTimeout()
                        if not self._pump():
                            self._drop_stalled_frame()
                            time.sleep_ms(1)
                        continue
                    if reply["id"] == rid or (reply["id"] == 0 and "nack" in reply):
                        # the RP2040 nacks a request it could not decode with id 0; only one
                        # request is on the wire, so it is this one
                        if "nack" in reply:
                            raise LinkNack()
                        return reply
                    self._inbox.append(reply)
        finally:
            self._dispatch()

    def poll(self):
        """Handle frames that arrived without a request (boot hello, NMEA sentences). Call it
        now and then when nothing else uses the link; requests do the same on their way."""
        try:
            with self._lock:
                self._pump()
                while True:
                    msg = self._next_frame()
                    if msg is None:
                        return
                    self._inbox.append(msg)
        finally:
            self._dispatch()

    def send(self, msg):
        """Send a request that gets no reply (beep, tone)."""
        with self._lock:
            self.uart.write(proto.frame(proto.encode(msg)))

    # --- internals ------------------------------------------------------- #
    def _take_id(self):
        rid = self._next_id
        self._next_id = rid + 1 if rid < 0x7FFFFFFF else 1
        return rid

    def _pump(self):
        n = self.uart.any()
        if not n:
            return False
        data = self.uart.read(n)
        if data:
            self._buf += data
            self._last_rx = time.ticks_ms()
            return True
        return False

    def _drop_stalled_frame(self):
        buf = self._buf
        if len(buf) >= proto.HEADER_SIZE and buf[:2] == proto.MAGIC \
                and time.ticks_diff(time.ticks_ms(), self._last_rx) > STALL_MS:
            self._buf = buf[1:]  # look for the next magic inside what that header claimed

    def _next_frame(self):
        while True:
            buf = self._buf
            i = buf.find(proto.MAGIC)
            if i < 0:
                # keep a trailing first magic byte: its partner may be on its way
                self._buf = buf[-1:] if buf and buf[-1] == proto.MAGIC[0] else b""
                return None
            if i:
                buf = self._buf = buf[i:]
            if len(buf) < proto.HEADER_SIZE:
                return None
            n = (buf[2] << 8) | buf[3]
            if n > MAX_PAYLOAD:
                self._buf = buf[1:]    # not a real header: look for the next magic
                continue
            end = proto.HEADER_SIZE + n
            if len(buf) < end:
                return None
            try:
                msg = proto.decode(buf[proto.HEADER_SIZE:end])
            except ValueError:
                self._buf = buf[1:]  # not a real frame: resync from just after its magic
                continue
            self._buf = buf[end:]
            return msg

    def _dispatch(self):
        # Runs without the lock, so a callback may use the link itself
        while True:
            try:
                msg = self._inbox.pop(0)
            except IndexError:  # empty, or another thread took the last one
                return
            if msg["id"] == 0 and "ping" in msg:
                self.hellos += 1        # the RP2040 announces a (re)start
            elif "nmea" in msg and self.on_nmea is not None:
                try:
                    self.on_nmea(msg["nmea"])
                except Exception as e:
                    logger.warning("indicator_rp2040: nmea callback error: %r", e)
            # late replies to requests that already timed out are dropped
