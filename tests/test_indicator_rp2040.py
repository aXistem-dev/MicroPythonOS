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
        self.busy_for = 0                     # report the card busy this many more times
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
        self.assertEqual(_errno(sd.rename, "/a", "/b"), errno.EPERM)
        self.assertEqual(_errno(sd.rmdir, "/tiles"), errno.EPERM)
        self.assertEqual(_errno(sd.open, "/nodir/x.bin", "wb"), errno.EIO)

    def test_format_asks_the_rp2040(self):
        rp, sd = make_sd()
        self.assertTrue(sd.format())
        self.assertEqual([m["sd_command"] for m in rp.received if "sd_command" in m], [proto.SD_FORMAT])
        rp.card = "none"
        self.assertFalse(sd.format())

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
        rp.devices[0x62] = bytearray(4)
        i2c.readfrom_mem(0x62, 0x3682, 3, addrsize=16)
        self.assertEqual(_i2c_requests(rp)[-1]["write_data"], b"\x36\x82")

    def test_absent_device_is_enodev(self):
        rp, i2c = make_i2c()
        self.assertEqual(_errno(i2c.readfrom_mem, 0x44, 0, 2), errno.ENODEV)
        self.assertEqual(_errno(i2c.writeto, 0x44, b"\x00"), errno.ENODEV)

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

    def test_beep(self):
        rp, b = self.make()
        b.beep(120)
        self.assertEqual([m["beep"] for m in rp.received if "beep" in m], [120])


if __name__ == "__main__":
    unittest.main()
