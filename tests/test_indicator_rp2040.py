"""indicator_rp2040 driver: the link to the SenseCAP Indicator's RP2040 co-processor and the
peripherals behind it (SD card, Grove I2C, buzzer), tested against an in-process fake of the
RP2040's peripheral-bridge firmware."""

import errno
import time
import unittest

from drivers.indicator_rp2040 import proto


# --- a fake RP2040 ------------------------------------------------------- #

class FakeRP2040:
    """Speaks interdevice.proto like the real firmware: answers requests (echoing the id),
    takes beep/tone without answering, serves an in-memory SD card and I2C devices."""

    PAGE = 16
    CHUNK = 4096

    def __init__(self):
        self.version = proto.INTERDEVICE_VERSION
        self.card = "ok"                      # "ok", "none", "busy"
        self.files = {}                       # "/path" -> bytearray
        self.dirs = {"/"}
        self.devices = {}                     # addr -> bytearray register file
        self.received = []                    # every decoded request
        self.drop = 0                         # swallow the next N requests
        self.nack_next = False
        self.prefix = b""                     # bytes sent ahead of the next response
        self.chunked = 0                      # deliver responses N bytes at a time

    # requests ------------------------------------------------------------ #
    def handle(self, msg):
        self.received.append(msg)
        if self.drop:
            self.drop -= 1
            return None
        if self.nack_next:
            self.nack_next = False
            return {"id": msg["id"], "nack": True}
        rid = msg["id"]
        if "ping" in msg:
            return {"id": rid, "pong": self.version}
        if "beep" in msg or "tone" in msg:
            return None
        if "i2c_scan" in msg:
            return {"id": rid, "i2c_scan_result": bytes(sorted(self.devices))}
        if "i2c_transaction" in msg:
            return {"id": rid, "i2c_result": self._i2c(msg["i2c_transaction"])}
        if "get_sd_info" in msg or "sd_command" in msg:
            return {"id": rid, "sd_info": self._info()}
        if "file_transfer" in msg:
            return {"id": rid, "file_transfer": self._file(msg["file_transfer"])}
        if "directory_listing" in msg:
            return {"id": rid, "directory_listing": self._list(msg["directory_listing"])}
        return {"id": rid, "nack": True}

    def _info(self):
        if self.card == "none":
            return {}
        if self.card == "busy":
            return {"busy": True}
        used = sum(len(v) for v in self.files.values())
        return {"present": True, "card_type": 3, "fat_type": 2, "card_size": 8 << 30,
                "used_bytes": used, "free_bytes": (8 << 30) - used, "stats_valid": True}

    def _i2c(self, t):
        dev = self.devices.get(t["address"])
        if dev is None:
            return {"status": proto.I2C_NACK_ADDRESS}
        w = t.get("write_data", b"")
        reg = w[0] if w else 0
        if len(w) > 1:
            dev[reg:reg + len(w) - 1] = w[1:]
        n = min(t.get("read_len", 0), 256)
        return {"status": proto.I2C_OK, "read_data": bytes(dev[reg:reg + n])}

    def _card(self):
        if self.card == "none":
            return proto.FILE_NO_CARD
        if self.card == "busy":
            return proto.FILE_BUSY
        return None

    def _file(self, f):
        op = f.get("operation", proto.GET)
        path = f.get("filepath", "")
        out = {"operation": op, "filepath": path, "offset": f.get("offset", 0)}
        bad = self._card()
        if bad is not None:
            out["status"] = bad
            return out
        if op == proto.GET:
            if path in self.dirs:
                out["status"] = proto.FILE_NOT_A_FILE
                return out
            data = self.files.get(path)
            if data is None:
                out["status"] = proto.FILE_NOT_FOUND
                return out
            off = f.get("offset", 0)
            if off > len(data):
                out["status"] = proto.FILE_OFFSET_CONFLICT
                return out
            n = f.get("length", 0) or self.CHUNK
            n = min(n, self.CHUNK)
            out.update(status=proto.FILE_OK, filedata=bytes(data[off:off + n]), file_size=len(data))
            return out
        if op in (proto.POST, proto.PUT):
            parent = path.rsplit("/", 1)[0] or "/"
            if parent not in self.dirs:
                out.update(status=proto.FILE_IO_ERROR, message="open failed")
                return out
            if op == proto.POST:
                if f.get("offset", 0):
                    out["status"] = proto.FILE_OFFSET_CONFLICT
                    return out
                self.files[path] = bytearray()
            data = self.files.setdefault(path, bytearray())
            if len(data) != f.get("offset", 0):
                out.update(status=proto.FILE_OFFSET_CONFLICT, file_size=len(data))
                return out
            data.extend(f.get("filedata", b""))
            out.update(status=proto.FILE_OK, file_size=len(data))
            return out
        if op == proto.DELETE:
            self.files.pop(path, None)
            out["status"] = proto.FILE_OK
            return out
        if op == proto.MKDIR:
            if path in self.files:
                out["status"] = proto.FILE_NOT_A_FILE
                return out
            parts = path.strip("/").split("/")
            for i in range(1, len(parts) + 1):
                self.dirs.add("/" + "/".join(parts[:i]))
            out["status"] = proto.FILE_OK
            return out
        out["status"] = proto.FILE_IO_ERROR
        return out

    def _list(self, req):
        d = req.get("directory", "/")
        bad = self._card()
        if bad is not None:
            return {"directory": d, "status": bad}
        if d in self.files:
            return {"directory": d, "status": proto.FILE_NOT_A_FILE}
        if d not in self.dirs:
            return {"directory": d, "status": proto.FILE_NOT_FOUND}
        base = d.rstrip("/") + "/"
        names = []
        for p in sorted(self.dirs):
            if p != d and p.startswith(base) and "/" not in p[len(base):]:
                names.append(p[len(base):] + "/")
        for p in sorted(self.files):
            if p.startswith(base) and "/" not in p[len(base):]:
                names.append(p[len(base):])
        off = req.get("offset", 0)
        return {"directory": d, "filenames": names[off:off + self.PAGE], "status": proto.FILE_OK,
                "total_count": len(names)}


class FakeUART:
    """machine.UART stand-in wired to a FakeRP2040: a written frame is decoded and handled at
    once, and the response bytes wait in the receive buffer."""

    def __init__(self, rp):
        self.rp = rp
        self.rx = b""
        self.tx = []
        self._inbuf = b""

    def write(self, data):
        self.tx.append(bytes(data))
        self._inbuf += bytes(data)
        while len(self._inbuf) >= 4:
            n = (self._inbuf[2] << 8) | self._inbuf[3]
            if len(self._inbuf) < 4 + n:
                break
            payload = self._inbuf[4:4 + n]
            self._inbuf = self._inbuf[4 + n:]
            resp = self.rp.handle(proto.decode(payload))
            if self.rp.prefix:
                self.rx += self.rp.prefix
                self.rp.prefix = b""
            if resp is not None:
                self.rx += proto.frame(proto.encode(resp))
        return len(data)

    def any(self):
        return min(len(self.rx), self.rp.chunked) if self.rp.chunked else len(self.rx)

    def read(self, n=-1):
        if not self.rx:
            return None
        k = self.any() if n is None or n < 0 else min(n, self.any())
        out = self.rx[:k]
        self.rx = self.rx[k:]
        return out


def make_link(**kw):
    from drivers.indicator_rp2040.link import Link
    rp = FakeRP2040()
    uart = FakeUART(rp)
    return rp, uart, Link(uart, **kw)


# --- link ---------------------------------------------------------------- #

class TestLink(unittest.TestCase):

    def test_ping_returns_the_peer_version(self):
        rp, uart, link = make_link()
        self.assertEqual(link.ping(), proto.INTERDEVICE_VERSION)
        self.assertTrue(link.available())

    def test_each_request_gets_its_own_id(self):
        rp, uart, link = make_link()
        link.ping()
        link.ping()
        ids = [m["id"] for m in rp.received]
        self.assertTrue(ids[0] != ids[1] and ids[0] > 0 and ids[1] > 0)

    def test_stale_reply_and_hello_are_skipped(self):
        rp, uart, link = make_link()
        stale = proto.frame(proto.encode({"id": 999, "pong": 2}))
        hello = proto.frame(proto.encode({"id": 0, "ping": 2}))
        rp.prefix = stale + hello
        self.assertEqual(link.ping(), 2)
        self.assertEqual(link.hellos, 1)

    def test_garbage_and_oversized_header_are_resynced(self):
        rp, uart, link = make_link()
        rp.prefix = b"\x00\xff\x94\x94\xc3\xff\xff junk"
        self.assertEqual(link.ping(), 2)

    def test_reply_arriving_in_small_pieces(self):
        rp, uart, link = make_link()
        rp.chunked = 3
        info = link.request({"get_sd_info": True})
        self.assertTrue(info["sd_info"]["present"])

    def test_missing_reply_times_out_and_the_link_recovers(self):
        from drivers.indicator_rp2040.link import LinkTimeout
        rp, uart, link = make_link(timeout_ms=60)
        rp.drop = 1
        t0 = time.ticks_ms()
        with self.assertRaises(LinkTimeout):
            link.ping()
        self.assertTrue(time.ticks_diff(time.ticks_ms(), t0) < 1000)
        self.assertEqual(link.ping(), 2)

    def test_timeout_is_an_oserror_etimedout(self):
        from drivers.indicator_rp2040.link import LinkTimeout
        e = LinkTimeout()
        self.assertTrue(isinstance(e, OSError))
        self.assertEqual(e.errno, errno.ETIMEDOUT)

    def test_nack_fails_fast(self):
        from drivers.indicator_rp2040.link import LinkNack
        rp, uart, link = make_link(timeout_ms=5000)
        rp.nack_next = True
        t0 = time.ticks_ms()
        with self.assertRaises(LinkNack):
            link.ping()
        self.assertTrue(time.ticks_diff(time.ticks_ms(), t0) < 1000)

    def test_tone_is_sent_without_waiting_for_a_reply(self):
        rp, uart, link = make_link(timeout_ms=5000)
        t0 = time.ticks_ms()
        link.send({"tone": {"frequency_hz": 440, "duration_ms": 100}})
        self.assertTrue(time.ticks_diff(time.ticks_ms(), t0) < 500)
        self.assertEqual(rp.received[-1]["tone"], {"frequency_hz": 440, "duration_ms": 100})

    def test_other_version_is_refused(self):
        from drivers.indicator_rp2040.link import LinkVersionError
        rp, uart, link = make_link()
        rp.version = 3
        with self.assertRaises(LinkVersionError):
            link.connect()
        self.assertFalse(link.available())

    def test_connect_on_a_silent_line_reports_unavailable(self):
        rp, uart, link = make_link(timeout_ms=40)
        rp.drop = 10
        self.assertFalse(link.connect(raise_errors=False))
        self.assertFalse(link.available())

    def test_two_threads_get_their_own_answers(self):
        import _thread
        rp, uart, link = make_link()
        rp.devices[0x44] = bytearray(b"\x11\x22\x33\x44")
        rp.devices[0x62] = bytearray(b"\xaa\xbb\xcc\xdd")
        results = {}
        done = []

        def worker(addr, expect):
            ok = True
            for _ in range(30):
                r = link.request({"i2c_transaction": {"address": addr, "write_data": b"\x00", "read_len": 4}})
                ok = ok and r["i2c_result"]["read_data"] == expect
            results[addr] = ok
            done.append(addr)

        _thread.start_new_thread(worker, (0x44, b"\x11\x22\x33\x44"))
        _thread.start_new_thread(worker, (0x62, b"\xaa\xbb\xcc\xdd"))
        t0 = time.ticks_ms()
        while len(done) < 2 and time.ticks_diff(time.ticks_ms(), t0) < 5000:
            time.sleep_ms(10)
        self.assertEqual(results, {0x44: True, 0x62: True})


if __name__ == "__main__":
    unittest.main()
