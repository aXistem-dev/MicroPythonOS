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
        self.nack0_next = False                # nack an undecodable request (id 0)
        self.prefix = b""                     # bytes sent ahead of the next response
        self.chunked = 0                      # deliver responses N bytes at a time
        self.busy_for = 0                     # report the card busy this many more times
        self.slow_format = 0                  # a format runs after the reply: sd_info busy N times
        self.info_busy = 0
        self.drop_after_handling = 0          # handle the next N requests, lose the reply

    # requests ------------------------------------------------------------ #
    def handle(self, msg):
        self.received.append(msg)
        if self.drop:
            self.drop -= 1
            return None
        if self.nack_next:
            self.nack_next = False
            return {"id": msg["id"], "nack": True}
        if self.nack0_next:
            self.nack0_next = False
            return {"id": 0, "nack": True}
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
            info = self._info()
            if msg.get("sd_command") == proto.SD_FORMAT and self.slow_format:
                self.info_busy = self.slow_format   # the reply is built before formatting starts
            return {"id": rid, "sd_info": info}
        if "file_transfer" in msg:
            return {"id": rid, "file_transfer": self._file(msg["file_transfer"])}
        if "directory_listing" in msg:
            return {"id": rid, "directory_listing": self._list(msg["directory_listing"])}
        return {"id": rid, "nack": True}

    def _info(self):
        if self.info_busy:
            self.info_busy -= 1
            return {"busy": True}
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
        if self.busy_for:
            self.busy_for -= 1
            return proto.FILE_BUSY
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
        self.log = []                         # "w" per write, "r" per read that returned bytes
        self._inbuf = b""

    def write(self, data):
        self.tx.append(bytes(data))
        self.log.append("w")
        self._inbuf += bytes(data)
        while len(self._inbuf) >= 4:
            n = (self._inbuf[2] << 8) | self._inbuf[3]
            if len(self._inbuf) < 4 + n:
                break
            payload = self._inbuf[4:4 + n]
            self._inbuf = self._inbuf[4 + n:]
            resp = self.rp.handle(proto.decode(payload))
            if resp is not None and self.rp.drop_after_handling:
                self.rp.drop_after_handling -= 1
                resp = None
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
        self.log.append("r")
        return out

    def readinto(self, buf):
        data = self.read(len(buf))
        if not data:
            return None
        buf[:len(data)] = data
        return len(data)


class BlockingUART(FakeUART):
    """A UART opened with a read timeout: replies only come in while the reader waits in
    read(), as they do when the RP2040 needs a moment to answer."""

    def __init__(self, rp):
        super().__init__(rp)
        self.later = b""

    def write(self, data):
        n = super().write(data)
        self.later += self.rx
        self.rx = b""
        return n

    def read(self, n=-1):
        if not self.rx and self.later:
            self.rx, self.later = self.later, b""
        return super().read(n)

    def readinto(self, buf):
        if not self.rx and self.later:
            self.rx, self.later = self.later, b""
        return super().readinto(buf)


def make_link(uart_class=FakeUART, **kw):
    from drivers.indicator_rp2040.link import Link
    rp = FakeRP2040()
    uart = uart_class(rp)
    return rp, uart, Link(uart, **kw)


def _get(path, offset):
    return {"file_transfer": {"operation": proto.GET, "filepath": path, "offset": offset,
                              "length": 4096}}


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

    def test_nmea_sentences_go_to_the_callback(self):
        rp, uart, link = make_link()
        got = []
        link.on_nmea = got.append
        rp.prefix = proto.frame(proto.encode({"id": 0, "nmea": "$GPGGA,123519"}))
        self.assertEqual(link.ping(), 2)
        self.assertEqual(got, ["$GPGGA,123519"])

    def test_poll_delivers_unsolicited_frames_without_a_request(self):
        rp, uart, link = make_link()
        got = []
        link.on_nmea = got.append
        uart.rx += proto.frame(proto.encode({"id": 0, "nmea": "$GPRMC,1"}))
        uart.rx += proto.frame(proto.encode({"id": 0, "ping": 2}))
        link.poll()
        self.assertEqual(got, ["$GPRMC,1"])
        self.assertEqual(link.hellos, 1)

    def test_garbage_and_oversized_header_are_resynced(self):
        rp, uart, link = make_link()
        rp.prefix = b"\x00\xff\x94\x94\xc3\xff\xff junk"
        self.assertEqual(link.ping(), 2)

    def test_more_garbage_than_the_receive_buffer_holds_is_skipped(self):
        rp, uart, link = make_link()
        rp.prefix = bytes(range(0x90)) * 200          # ~29 KB, no magic in it
        self.assertEqual(link.ping(), 2)
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

    def test_false_header_with_a_small_length_does_not_eat_the_reply(self):
        rp, uart, link = make_link(timeout_ms=500)
        rp.prefix = b"\x94\xc3\x00\x10"
        self.assertEqual(link.ping(), 2)
        self.assertEqual(link.ping(), 2)

    def test_false_header_with_a_large_length_is_dropped_once_the_line_is_quiet(self):
        rp, uart, link = make_link(timeout_ms=500)
        rp.prefix = b"\x94\xc3\x10\x00"
        self.assertEqual(link.ping(), 2)
        self.assertEqual(link.ping(), 2)

    def test_a_request_the_rp2040_cannot_decode_fails_fast(self):
        from drivers.indicator_rp2040.link import LinkNack
        rp, uart, link = make_link(timeout_ms=5000)
        rp.nack0_next = True
        t0 = time.ticks_ms()
        with self.assertRaises(LinkNack):
            link.ping()
        self.assertTrue(time.ticks_diff(time.ticks_ms(), t0) < 1000)
        self.assertEqual(link.ping(), 2)

    def test_nmea_callback_runs_outside_the_link_lock(self):
        # a callback that uses the link itself (e.g. logging sentences to the SD card) must work
        rp, uart, link = make_link()
        locked = []
        link.on_nmea = lambda sentence: locked.append(link._lock.locked())
        rp.prefix = proto.frame(proto.encode({"id": 0, "nmea": "$GPGGA,1"}))
        link.ping()
        uart.rx += proto.frame(proto.encode({"id": 0, "nmea": "$GPGGA,2"}))
        link.poll()
        self.assertEqual(locked, [False, False])

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

    def test_a_request_from_inside_a_request_on_the_same_thread_fails_fast(self):
        # MicroPython runs scheduled work (LVGL's timers and events) between bytecodes of
        # whichever thread is running: a UI callback that beeps or reads the card can run
        # inside a request this thread is waiting on, and would wait for its own lock
        from drivers.indicator_rp2040.link import LinkBusy
        rp, uart, link = make_link()
        nested = []
        orig = uart.write

        def write(data):
            if not nested:
                nested.append("ui")
                try:
                    link.request({"ping": 2})
                except LinkBusy as e:
                    nested.append(e.errno)
                try:
                    link.send({"beep": 1})
                except LinkBusy:
                    nested.append("send busy")
            return orig(data)

        uart.write = write
        self.assertEqual(link.ping(), 2)
        self.assertEqual(nested, ["ui", sdfs.EBUSY, "send busy"])
        uart.write = orig
        self.assertEqual(link.ping(), 2)

    def test_waiting_for_a_reply_blocks_in_the_uart_instead_of_sleeping(self):
        # a blocking read lets other threads run until the reply's first byte is in; a sleep
        # wakes up late (a 1 ms sleep takes ~5 ms on the device)
        from drivers.indicator_rp2040 import link as link_module
        rp, uart, link = make_link(BlockingUART)
        sleeps = []

        class Clock:
            ticks_ms = time.ticks_ms
            ticks_diff = time.ticks_diff
            ticks_add = time.ticks_add

            def sleep_ms(ms):
                sleeps.append(ms)
                time.sleep_ms(ms)

        link_module.time = Clock
        try:
            self.assertEqual(link.ping(), 2)
        finally:
            link_module.time = time
        self.assertEqual(sleeps, [])


class TestLinkPipeline(unittest.TestCase):

    def setUp(self):
        self.rp, self.uart, self.link = make_link()
        self.data = bytes(range(256)) * 80              # 20480 bytes: five chunks
        self.rp.files["/f"] = bytearray(self.data)

    def test_replies_come_back_in_request_order(self):
        msgs = [_get("/f", off) for off in (0, 4096, 8192, 12288, 16384)]
        replies = self.link.request_many(msgs)
        self.assertEqual(b"".join(r["file_transfer"]["filedata"] for r in replies), self.data)

    def test_several_requests_are_on_the_wire_before_the_first_reply_is_read(self):
        msgs = [_get("/f", off) for off in (0, 4096, 8192, 12288, 16384)]
        self.link.request_many(msgs, window=3)
        first_read = self.uart.log.index("r")
        self.assertEqual(self.uart.log[:first_read], ["w", "w", "w"])
        self.assertEqual(self.uart.log.count("w"), 5)

    def test_unsolicited_frames_between_replies_are_still_handled(self):
        self.rp.prefix = proto.frame(proto.encode({"id": 0, "ping": 2}))
        replies = self.link.request_many([_get("/f", 0), _get("/f", 4096)])
        self.assertEqual(len(replies), 2)
        self.assertEqual(self.link.hellos, 1)

    def test_a_lost_reply_times_out_and_the_link_recovers(self):
        from drivers.indicator_rp2040.link import LinkTimeout
        self.link.timeout_ms = 40
        self.rp.drop = 1
        with self.assertRaises(LinkTimeout):
            self.link.request_many([_get("/f", 0), _get("/f", 4096)])
        self.assertEqual(self.link.ping(), 2)

    def test_a_nack_fails_the_batch(self):
        from drivers.indicator_rp2040.link import LinkNack
        self.rp.nack_next = True
        with self.assertRaises(LinkNack):
            self.link.request_many([_get("/f", 0), _get("/f", 4096)])
        self.assertEqual(self.link.ping(), 2)


# --- SD card as a filesystem ------------------------------------------- #

from drivers.indicator_rp2040 import sdfs


def make_sd(**kw):
    from drivers.indicator_rp2040.sdfs import SDCard
    rp, uart, link = make_link()
    return rp, SDCard(link, busy_wait_ms=1, **kw)


def _errno(fn, *args):
    try:
        fn(*args)
    except OSError as e:
        return e.errno
    return None


class TestSDNoCard(unittest.TestCase):

    def test_every_operation_says_no_device(self):
        rp, sd = make_sd()
        rp.card = "none"
        self.assertEqual(_errno(sd.stat, "/a.txt"), errno.ENODEV)
        self.assertEqual(_errno(lambda: list(sd.ilistdir("/"))), errno.ENODEV)
        self.assertEqual(_errno(sd.open, "/a.txt", "rb"), errno.ENODEV)
        self.assertEqual(_errno(sd.open, "/a.txt", "wb"), errno.ENODEV)
        self.assertEqual(_errno(sd.statvfs, "/"), errno.ENODEV)
        self.assertFalse(sd.present())

    def test_a_card_still_mounting_is_waited_for(self):
        rp, sd = make_sd(busy_retries=10)
        rp.files["/a.txt"] = bytearray(b"hello")
        rp.busy_for = 3
        with sd.open("/a.txt", "rb") as f:
            self.assertEqual(f.read(), b"hello")

    def test_an_empty_slot_retrying_its_mount_answers_at_once(self):
        # With no card the RP2040 retries mounting all the time and reports "busy" meanwhile:
        # once a reply said "no card", busy replies mean the slot is still empty.
        rp, sd = make_sd(busy_retries=50)
        rp.card = "none"
        self.assertEqual(_errno(sd.stat, "/a.txt"), errno.ENODEV)
        rp.busy_for = 100
        n = len(rp.received)
        self.assertEqual(_errno(sd.stat, "/a.txt"), errno.ENODEV)
        self.assertEqual(_errno(lambda: list(sd.ilistdir("/"))), errno.ENODEV)
        self.assertEqual(len(rp.received) - n, 2)

    def test_a_card_inserted_later_is_found(self):
        rp, sd = make_sd(busy_retries=50)
        rp.card = "none"
        self.assertEqual(_errno(sd.stat, "/a.txt"), errno.ENODEV)
        rp.card = "ok"
        rp.files["/a.txt"] = bytearray(b"hello")
        rp.busy_for = 1                       # the mount that finds the card
        self.assertEqual(_errno(sd.stat, "/a.txt"), errno.ENODEV)
        self.assertEqual(sd.stat("/a.txt")[6], 5)

    def test_a_card_busy_too_long_is_ebusy(self):
        rp, sd = make_sd(busy_retries=3)
        rp.files["/a.txt"] = bytearray(b"hello")
        rp.busy_for = 100
        self.assertEqual(_errno(sd.open, "/a.txt", "rb"), sdfs.EBUSY)


class TestSDRead(unittest.TestCase):

    DATA = bytes(range(256)) * 40          # 10240 bytes: three chunks

    def setUp(self):
        self.rp, self.sd = make_sd()
        self.rp.files["/tiles/12/a.png"] = bytearray(self.DATA)
        self.rp.dirs.update(("/tiles", "/tiles/12"))

    def test_read_all(self):
        with self.sd.open("/tiles/12/a.png", "rb") as f:
            self.assertEqual(f.read(), self.DATA)
        gets = [m["file_transfer"] for m in self.rp.received if "file_transfer" in m]
        self.assertTrue(all(g["length"] <= 4096 for g in gets))

    def test_read_in_odd_sizes(self):
        out = b""
        with self.sd.open("/tiles/12/a.png", "rb") as f:
            while True:
                part = f.read(1000)
                if not part:
                    break
                out += part
        self.assertEqual(out, self.DATA)

    def test_seek_tell_and_readinto(self):
        f = self.sd.open("/tiles/12/a.png", "rb")
        f.seek(5000)
        self.assertEqual(f.tell(), 5000)
        buf = bytearray(300)
        self.assertEqual(f.readinto(buf), 300)
        self.assertEqual(bytes(buf), self.DATA[5000:5300])
        f.seek(-10, 2)
        self.assertEqual(f.read(), self.DATA[-10:])
        f.seek(-20, 1)
        self.assertEqual(f.read(5), self.DATA[-20:-15])
        self.assertEqual(f.read(0), b"")
        f.seek(0, 2)
        self.assertEqual(f.read(10), b"")
        f.close()

    def test_missing_file_and_directory(self):
        self.assertEqual(_errno(self.sd.open, "/nope.png", "rb"), errno.ENOENT)
        self.assertEqual(_errno(self.sd.open, "/tiles", "rb"), errno.EISDIR)

    def test_stat(self):
        st = self.sd.stat("/tiles/12/a.png")
        self.assertEqual(st[0], 0x8000)
        self.assertEqual(st[6], len(self.DATA))
        self.assertEqual(self.sd.stat("/tiles")[0], 0x4000)
        self.assertEqual(self.sd.stat("/")[0], 0x4000)
        self.assertEqual(_errno(self.sd.stat, "/nope"), errno.ENOENT)

    def test_text_mode(self):
        self.rp.files["/notes.txt"] = bytearray("one\ntwo caf\u00e9\nthree".encode())
        with self.sd.open("/notes.txt", "r") as f:
            self.assertEqual(f.readline(), "one\n")
            self.assertEqual(f.read(), "two caf\u00e9\nthree")
        with self.sd.open("/notes.txt") as f:
            self.assertEqual([line for line in f], ["one\n", "two caf\u00e9\n", "three"])

    def test_a_reply_lost_once_is_retried(self):
        self.rp.drop = 1
        self.sd.link.timeout_ms = 40
        with self.sd.open("/tiles/12/a.png", "rb") as f:
            self.assertEqual(f.read(), self.DATA)

    def test_lines_across_chunk_boundaries(self):
        lines = [(b"line %d " % i) + b"x" * (i * 37 % 300) + b"\n" for i in range(120)]
        self.rp.files["/log.txt"] = bytearray(b"".join(lines))
        with self.sd.open("/log.txt", "rb") as f:
            self.assertEqual([f.readline() for _ in lines], lines)
            self.assertEqual(f.readline(), b"")
        with self.sd.open("/log.txt", "rb") as f:
            f.seek(4090)
            self.assertEqual(f.readline(5), b"".join(lines)[4090:4095])

    def test_a_whole_file_read_asks_for_its_chunks_together(self):
        uart = self.sd.link.uart
        with self.sd.open("/tiles/12/a.png", "rb") as f:
            uart.log.clear()
            self.assertEqual(f.read(), self.DATA)
        # chunks two and three: both requests go out before the first reply is read
        self.assertEqual(uart.log[:2], ["w", "w"])

    def test_a_short_read_asks_only_for_the_chunk_it_needs(self):
        with self.sd.open("/tiles/12/a.png", "rb") as f:
            n = len(self.rp.received)
            self.assertEqual(f.read(5000)[-904:], self.DATA[4096:5000])
            self.assertEqual(len(self.rp.received) - n, 1)

    def test_a_reply_lost_during_a_whole_file_read_is_retried(self):
        self.sd.link.timeout_ms = 40
        with self.sd.open("/tiles/12/a.png", "rb") as f:
            self.rp.drop = 1
            self.assertEqual(f.read(), self.DATA)

    def test_a_card_busy_during_a_whole_file_read_is_waited_for(self):
        with self.sd.open("/tiles/12/a.png", "rb") as f:
            self.rp.busy_for = 2
            self.assertEqual(f.read(), self.DATA)

    def test_a_big_file_is_read_whole_in_windows(self):
        big = bytes(range(251)) * 400            # 100400 bytes
        self.rp.files["/big.bin"] = bytearray(big)
        with self.sd.open("/big.bin", "rb") as f:
            self.assertEqual(f.read(), big)


class TestSDList(unittest.TestCase):

    def test_listing_pages_through_a_big_directory(self):
        rp, sd = make_sd()
        rp.dirs.add("/tiles")
        for i in range(40):
            rp.files["/f%02d.txt" % i] = bytearray(b"x")
        names = [(e[0], e[1]) for e in sd.ilistdir("/")]
        self.assertEqual(names[0], ("tiles", 0x4000))
        self.assertEqual(len(names), 41)
        self.assertEqual(names[-1], ("f39.txt", 0x8000))

    def test_listing_a_file_or_nothing(self):
        rp, sd = make_sd()
        rp.files["/a.txt"] = bytearray(b"x")
        self.assertEqual(_errno(lambda: list(sd.ilistdir("/a.txt"))), sdfs.ENOTDIR)
        self.assertEqual(_errno(lambda: list(sd.ilistdir("/nope"))), errno.ENOENT)


class TestSDWrite(unittest.TestCase):

    def test_write_in_chunks(self):
        rp, sd = make_sd()
        data = bytes(range(251)) * 50       # 12550 bytes
        with sd.open("/out.bin", "wb") as f:
            for i in range(0, len(data), 777):
                f.write(data[i:i + 777])
        self.assertEqual(bytes(rp.files["/out.bin"]), data)
        puts = [m["file_transfer"] for m in rp.received if "file_transfer" in m]
        self.assertTrue(all(len(p.get("filedata", b"")) <= 4096 for p in puts))

    def test_overwrite_and_append(self):
        rp, sd = make_sd()
        rp.files["/log.txt"] = bytearray(b"old content")
        with sd.open("/log.txt", "w") as f:
            f.write("first\n")
        with sd.open("/log.txt", "a") as f:
            f.write("second\n")
        with sd.open("/new.txt", "ab") as f:
            f.write(b"fresh")
        self.assertEqual(bytes(rp.files["/log.txt"]), b"first\nsecond\n")
        self.assertEqual(bytes(rp.files["/new.txt"]), b"fresh")

    def test_a_chunk_whose_reply_was_lost_is_not_written_twice(self):
        rp, sd = make_sd()
        sd.link.timeout_ms = 40
        f = sd.open("/x.bin", "wb")
        f.write(b"a" * 5000)
        rp.drop_after_handling = 1
        f.close()
        self.assertEqual(bytes(rp.files["/x.bin"]), b"a" * 5000)

    def test_mkdir_remove_and_unsupported(self):
        rp, sd = make_sd()
        sd.mkdir("/tiles/12/2100")
        self.assertTrue("/tiles/12/2100" in rp.dirs)
        with sd.open("/tiles/12/2100/1360.png", "wb") as f:
            f.write(b"png")
        sd.remove("/tiles/12/2100/1360.png")
        self.assertFalse("/tiles/12/2100/1360.png" in rp.files)
        self.assertEqual(_errno(sd.rename, "/a", "/b"), 95)   # EOPNOTSUPP
        self.assertEqual(_errno(sd.rmdir, "/tiles"), 95)
        self.assertEqual(_errno(sd.open, "/nodir/x.bin", "wb"), errno.EIO)

    def test_format_asks_the_rp2040(self):
        rp, sd = make_sd()
        self.assertTrue(sd.format())
        self.assertEqual([m["sd_command"] for m in rp.received if "sd_command" in m], [proto.SD_FORMAT])
        rp.card = "none"
        self.assertFalse(sd.format())

    def test_format_waits_until_the_rp2040_has_formatted(self):
        rp, sd = make_sd()
        rp.slow_format = 3
        self.assertTrue(sd.format())
        self.assertEqual(rp.info_busy, 0)          # it asked until the card was back

    def test_format_of_an_unformatted_card_is_waited_for(self):
        rp, sd = make_sd()
        rp.card = "busy"                            # the reply to the command says busy
        rp.slow_format = 2

        def card_back(msg, orig=rp.handle):
            if rp.info_busy == 0 and len([m for m in rp.received if "get_sd_info" in m]) >= 2:
                rp.card = "ok"
            return orig(msg)

        rp.handle = card_back
        self.assertTrue(sd.format())

    def test_write_after_close_is_refused(self):
        rp, sd = make_sd()
        f = sd.open("/x.bin", "wb")
        f.close()
        self.assertEqual(_errno(f.write, b"late"), errno.EBADF)

    def test_unsupported_modes_are_refused(self):
        rp, sd = make_sd()
        self.assertEqual(_errno(sd.open, "/x.bin", "r+b"), errno.EINVAL)
        self.assertEqual(_errno(sd.open, "/x.bin", "xb"), errno.EINVAL)

    def test_too_long_a_path_is_refused_before_it_reaches_the_rp2040(self):
        rp, sd = make_sd()
        sent = len(rp.received)
        self.assertEqual(_errno(sd.open, "/" + "a" * 300, "rb"), 36)   # ENAMETOOLONG
        self.assertEqual(len(rp.received), sent)

    def test_large_write_in_one_call(self):
        rp, sd = make_sd()
        data = bytes(range(256)) * 50                  # 12800 bytes: three full chunks and a tail
        with sd.open("/big.bin", "wb") as f:
            self.assertEqual(f.write(data), len(data))
        self.assertEqual(bytes(rp.files["/big.bin"]), data)

    def test_text_write_counts_characters(self):
        rp, sd = make_sd()
        with sd.open("/t.txt", "w") as f:
            self.assertEqual(f.write("éé"), 2)

    def test_statvfs(self):
        rp, sd = make_sd()
        rp.files["/a"] = bytearray(8192)
        st = sd.statvfs("/")
        self.assertEqual(st[0] * st[2], 8 << 30)
        self.assertEqual(st[0] * st[3], (8 << 30) - 8192)


class TestSDMounted(unittest.TestCase):

    def test_os_functions_through_a_mount(self):
        import os
        rp, sd = make_sd()
        rp.dirs.add("/maps")
        rp.files["/maps/a.txt"] = bytearray(b"tile")
        os.mount(sd, "/sdtest")
        try:
            self.assertEqual(sorted(os.listdir("/sdtest")), ["maps"])
            self.assertEqual(os.listdir("/sdtest/maps"), ["a.txt"])
            with open("/sdtest/maps/a.txt", "rb") as f:
                self.assertEqual(f.read(), b"tile")
            self.assertEqual(os.stat("/sdtest/maps/a.txt")[6], 4)
            with open("/sdtest/maps/b.txt", "w") as f:
                f.write("new")
            self.assertEqual(bytes(rp.files["/maps/b.txt"]), b"new")
        finally:
            os.umount("/sdtest")


    def test_json_and_print_work_on_card_files(self):
        import json
        import os
        rp, sd = make_sd()
        os.mount(sd, "/sdtest")
        try:
            with open("/sdtest/prefs.json", "w") as f:
                json.dump({"a": 1, "b": [2, 3]}, f)
            with open("/sdtest/prefs.json") as f:
                self.assertEqual(json.load(f), {"a": 1, "b": [2, 3]})
            with open("/sdtest/log.txt", "w") as f:
                print("line", 1, file=f)
            self.assertEqual(bytes(rp.files["/log.txt"]), b"line 1\n")
        finally:
            os.umount("/sdtest")

# --- Grove I2C ----------------------------------------------------------- #

def make_i2c():
    from drivers.indicator_rp2040.i2c import RemoteI2C
    rp, uart, link = make_link()
    return rp, RemoteI2C(link)


def _i2c_requests(rp):
    return [m["i2c_transaction"] for m in rp.received if "i2c_transaction" in m]


class TestGroveI2C(unittest.TestCase):

    def test_scan_empty_and_with_a_device(self):
        rp, i2c = make_i2c()
        self.assertEqual(i2c.scan(), [])
        rp.devices[0x44] = bytearray(8)
        rp.devices[0x62] = bytearray(8)
        self.assertEqual(i2c.scan(), [0x44, 0x62])

    def test_register_reads_and_writes(self):
        rp, i2c = make_i2c()
        rp.devices[0x44] = bytearray(b"\x10\x11\x12\x13\x14\x15")
        self.assertEqual(i2c.readfrom_mem(0x44, 1, 2), b"\x11\x12")
        buf = bytearray(3)
        i2c.readfrom_mem_into(0x44, 2, buf)
        self.assertEqual(bytes(buf), b"\x12\x13\x14")
        i2c.writeto_mem(0x44, 4, b"\xaa\xbb")
        self.assertEqual(bytes(rp.devices[0x44][4:6]), b"\xaa\xbb")
        self.assertEqual(i2c.writeto(0x44, b"\x00\x01"), 2)
        self.assertEqual(i2c.readfrom(0x44, 2), b"\x01\x11")
        i2c.writevto(0x44, (b"\x03", b"\x33"))
        self.assertEqual(rp.devices[0x44][3], 0x33)

    def test_write_without_stop_joins_the_following_read(self):
        rp, i2c = make_i2c()
        rp.devices[0x44] = bytearray(b"\x00\x01\x02\x03")
        i2c.writeto(0x44, b"\x02", False)
        out = bytearray(2)
        i2c.readfrom_into(0x44, out)
        self.assertEqual(bytes(out), b"\x02\x03")
        self.assertEqual(_i2c_requests(rp)[-1], {"address": 0x44, "write_data": b"\x02", "read_len": 2})
        self.assertEqual(len(_i2c_requests(rp)), 1)

    def test_sixteen_bit_register_address(self):
        rp, i2c = make_i2c()
        rp.devices[0x62] = bytearray(0x40)   # the fake keys registers on the first address byte
        i2c.readfrom_mem(0x62, 0x3682, 3, addrsize=16)
        self.assertEqual(_i2c_requests(rp)[-1]["write_data"], b"\x36\x82")

    def test_absent_device_is_enodev(self):
        rp, i2c = make_i2c()
        self.assertEqual(_errno(i2c.readfrom_mem, 0x44, 0, 2), errno.ENODEV)
        self.assertEqual(_errno(i2c.writeto, 0x44, b"\x00"), errno.ENODEV)

    def test_a_short_read_is_an_error(self):
        rp, i2c = make_i2c()
        rp.devices[0x44] = bytearray(4)                 # only 4 registers answer
        with self.assertRaises(OSError):
            i2c.readfrom_mem(0x44, 2, 8)

    def test_any_whole_byte_address_size(self):
        rp, i2c = make_i2c()
        rp.devices[0x50] = bytearray(16)
        i2c.readfrom_mem(0x50, 0x000001, 1, addrsize=24)
        sent = _i2c_requests(rp)[-1]["write_data"]
        self.assertEqual(bytes(sent), b"\x00\x00\x01")

    def test_too_long_a_read(self):
        rp, i2c = make_i2c()
        rp.devices[0x44] = bytearray(8)
        with self.assertRaises(ValueError):
            i2c.readfrom(0x44, 300)


# --- buzzer ---------------------------------------------------------------- #

def _tones(rp):
    return [(m["tone"]["frequency_hz"], m["tone"]["duration_ms"]) for m in rp.received if "tone" in m]


class TestBuzzer(unittest.TestCase):

    def make(self):
        from drivers.indicator_rp2040.buzzer import RemoteBuzzer
        rp, uart, link = make_link()
        return rp, RemoteBuzzer(link)

    def test_notes_as_the_rtttl_player_plays_them(self):
        rp, b = self.make()
        b.freq(523)
        b.duty_u16(20000)
        b.duty_u16(0)
        b.freq(659)
        b.duty_u16(20000)
        b.duty_u16(0)
        self.assertEqual(_tones(rp), [(523, 0), (0, 0), (659, 0), (0, 0)])

    def test_changing_pitch_while_sounding(self):
        rp, b = self.make()
        b.freq(440)
        b.duty_u16(1000)
        b.freq(880)
        b.freq(880)
        self.assertEqual(_tones(rp), [(440, 0), (880, 0)])
        self.assertEqual(b.freq(), 880)

    def test_nothing_is_sent_while_silent_or_unchanged(self):
        rp, b = self.make()
        b.freq(440)
        b.duty_u16(0)
        b.duty_u16(500)
        b.duty_u16(600)
        self.assertEqual(_tones(rp), [(440, 0)])

    def test_deinit_silences(self):
        rp, b = self.make()
        b.freq(440)
        b.duty_u16(1000)
        b.deinit()
        self.assertEqual(_tones(rp)[-1], (0, 0))

    def test_beep_length_is_kept_in_range(self):
        rp, bz = self.make()
        bz.beep(100000)
        bz.beep(-5)
        self.assertEqual([m["beep"] for m in rp.received if "beep" in m], [65535, 0])

    def test_beep(self):
        rp, b = self.make()
        b.beep(120)
        self.assertEqual([m["beep"] for m in rp.received if "beep" in m], [120])


if __name__ == "__main__":
    unittest.main()
