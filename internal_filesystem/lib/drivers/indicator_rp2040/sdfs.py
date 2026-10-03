# The SD card in the RP2040's slot as a MicroPython VFS: os.mount(SDCard(link), "/sd") and the
# usual open()/os.listdir()/os.stat() work on it. Reads are ranged 4 KB GETs: a read that spans
# several chunks asks for them together (up to READ_AHEAD at once) and caches what came back;
# writes are buffered into 4 KB appends.

import errno
import io
import time

from . import proto
from .link import LinkError, LinkTimeout

CHUNK = 4096
READ_AHEAD = 8              # chunks one read may fetch at once (32 KB)
_DIR, _FILE = 0x4000, 0x8000

# MicroPython's errno module leaves these out; the POSIX values
EBUSY = getattr(errno, "EBUSY", 16)
ENOTDIR = getattr(errno, "ENOTDIR", 20)
ENAMETOOLONG = getattr(errno, "ENAMETOOLONG", 36)
EOPNOTSUPP = getattr(errno, "EOPNOTSUPP", 95)

MAX_PATH = 255              # bytes, the firmware's filepath limit (256 with the terminating NUL)

_ERRNO = {
    proto.FILE_NO_CARD: errno.ENODEV,
    proto.FILE_BUSY: EBUSY,
    proto.FILE_NOT_FOUND: errno.ENOENT,
    proto.FILE_NOT_A_FILE: errno.EISDIR,
    proto.FILE_IO_ERROR: errno.EIO,
    proto.FILE_OFFSET_CONFLICT: errno.EIO,
    proto.FILE_UNSPECIFIED: errno.EIO,
}


class SDCard:
    """`busy_retries` × `busy_wait_ms` is how long a card that is still mounting is waited for."""

    def __init__(self, link, busy_retries=30, busy_wait_ms=100):
        self.link = link
        self.busy_retries = busy_retries
        self.busy_wait_ms = busy_wait_ms
        self._cwd = "/"
        # With an empty slot the RP2040 keeps retrying the mount and answers "busy" while it
        # does (most of the time). Once it said "no card", busy means the slot is still empty.
        self._empty = False

    # --- card ------------------------------------------------------------ #
    def info(self):
        """The RP2040's SdCardInfo (present, card_type, fat_type, sizes, busy, unformatted)."""
        info = self.link.request({"get_sd_info": True})["sd_info"]
        if info["present"]:
            self._empty = False
        elif not info["busy"]:
            self._empty = True
        return info

    def present(self):
        try:
            return self.info()["present"]
        except OSError:
            return False

    def command(self, cmd):
        """proto.SD_MOUNT / SD_EJECT / SD_FORMAT. The RP2040 answers at once with the card info as
        it is at that moment; the mount or format itself happens afterwards."""
        self._empty = False
        return self.link.request({"sd_command": cmd})["sd_info"]

    def format(self, timeout_ms=120000):
        """Wipe the card and put a fresh FAT on it (the RP2040 does it). Waits for the format and
        the mount after it; True when the fresh card is mounted."""
        info = self.command(proto.SD_FORMAT)
        seen_busy = info["busy"]
        settled = 0
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
            time.sleep_ms(self.busy_wait_ms)
            info = self.info()
            if info["busy"]:
                seen_busy = True
                continue
            settled += 1
            # done once the busy spell is over (or it never showed: the format was quicker
            # than our polling)
            if seen_busy or settled > self.busy_retries:
                return bool(info["present"])
        raise OSError(EBUSY)

    # --- VFS protocol ---------------------------------------------------- #
    def mount(self, readonly, mkfs):
        pass

    def umount(self):
        pass

    def chdir(self, path):
        p = self._abs(path)
        if self.stat(p)[0] != _DIR:
            raise OSError(ENOTDIR)
        self._cwd = p

    def getcwd(self):
        return self._cwd

    def ilistdir(self, path="/"):
        d = self._abs(path)
        offset = 0
        while True:
            r = self._call({"directory_listing": {"directory": d, "offset": offset}},
                           "directory_listing")
            status = r["status"]
            if status == proto.FILE_NOT_A_FILE:
                raise OSError(ENOTDIR)
            if status != proto.FILE_OK:
                raise OSError(_ERRNO.get(status, errno.EIO))
            names = r["filenames"]
            for name in names:
                if name.endswith("/"):
                    yield (name[:-1], _DIR, 0)
                else:
                    yield (name, _FILE, 0)
            offset += len(names)
            if not names or offset >= r["total_count"]:
                return

    def stat(self, path):
        p = self._abs(path)
        if p == "/":
            return (_DIR, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        r = self._get(p, 0, 1)
        if r["status"] == proto.FILE_NOT_A_FILE:
            return (_DIR, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        _check(r)
        return (_FILE, 0, 0, 0, 0, 0, r["file_size"], 0, 0, 0)

    def statvfs(self, path):
        info = self._ready_info()
        bsize = 512
        blocks = info["card_size"] // bsize
        free = info["free_bytes"] // bsize if info["stats_valid"] else 0
        return (bsize, bsize, blocks, free, free, 0, 0, 0, 0, 255)

    def open(self, path, mode="r"):
        if "+" in mode or "x" in mode:
            raise OSError(errno.EINVAL)
        f = SDFile(self, self._abs(path), mode)
        return f if "b" in mode else _TextFile(f)

    def mkdir(self, path):
        r = self._file(proto.MKDIR, self._abs(path))
        if r["status"] == proto.FILE_NOT_A_FILE:
            raise OSError(errno.EEXIST)
        _check(r)

    def remove(self, path):
        _check(self._file(proto.DELETE, self._abs(path)))

    def rmdir(self, path):
        raise OSError(EOPNOTSUPP)        # not offered by the RP2040 firmware

    def rename(self, old, new):
        raise OSError(EOPNOTSUPP)        # not offered by the RP2040 firmware

    # --- requests -------------------------------------------------------- #
    def _abs(self, path):
        if not path:
            return self._cwd
        if not path.startswith("/"):
            path = self._cwd.rstrip("/") + "/" + path
        parts = []
        for part in path.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        path = "/" + "/".join(parts)
        if len(path.encode("utf-8")) > MAX_PATH:
            raise OSError(ENAMETOOLONG)
        return path

    def _call(self, msg, member, retry_timeout=True):
        """Send a file or listing request; wait out a busy card, retry a lost reply once."""
        busy = 0
        timeouts = 0
        while True:
            try:
                r = self.link.request(msg)[member]
            except LinkTimeout:
                timeouts += 1
                if not retry_timeout or timeouts > 1:
                    raise
                continue
            status = r["status"]
            if status != proto.FILE_BUSY:
                self._empty = status == proto.FILE_NO_CARD
                return r
            if self._empty:
                raise OSError(errno.ENODEV)
            busy += 1
            if busy > self.busy_retries:
                raise OSError(EBUSY)
            time.sleep_ms(self.busy_wait_ms)

    def _file(self, op, path, retry_timeout=True, **fields):
        ft = {"operation": op, "filepath": path}
        ft.update(fields)
        return self._call({"file_transfer": ft}, "file_transfer", retry_timeout)

    def _get(self, path, offset, length):
        return self._file(proto.GET, path, offset=offset, length=length)

    def _get_many(self, path, offsets):
        """Chunks of one file, asked for together. A busy card, a lost reply or a refusal
        sends them again the careful way: one at a time, with the busy waits and a retry."""
        msgs = [{"file_transfer": {"operation": proto.GET, "filepath": path, "offset": off,
                                   "length": CHUNK}} for off in offsets]
        try:
            rs = [r["file_transfer"] for r in self.link.request_many(msgs)]
        except LinkError:
            rs = None
        if rs is None or any(r["status"] == proto.FILE_BUSY for r in rs):
            return [self._get(path, off, CHUNK) for off in offsets]
        self._empty = rs[-1]["status"] == proto.FILE_NO_CARD
        return rs

    def _ready_info(self):
        for _ in range(self.busy_retries + 1):
            info = self.info()
            if info["present"]:
                return info
            if not info["busy"] or self._empty:
                raise OSError(errno.ENODEV)
            time.sleep_ms(self.busy_wait_ms)
        raise OSError(EBUSY)


def _check(r):
    if r["status"] != proto.FILE_OK:
        raise OSError(_ERRNO.get(r["status"], errno.EIO))


class SDFile(io.IOBase):
    """A binary file on the card. Modes: r, w, a (with or without b). As an io.IOBase stream it
    also works where MicroPython needs a real stream (json.load, print(file=...))."""

    def __init__(self, sd, path, mode):
        self.sd = sd
        self.path = path
        self.closed = False
        self._pos = 0
        self._chunks = []                # [(offset, data)]: the chunks fetched last
        self._wbuf = b""
        if "w" in mode or "a" in mode:
            self._writing = True
            size = 0
            if "a" in mode:
                try:
                    size = sd.stat(path)[6]
                except OSError as e:
                    if e.errno != errno.ENOENT:
                        raise
                    size = -1
            if size <= 0:
                _check(sd._file(proto.POST, path, offset=0, filedata=b""))   # create / truncate
                size = 0
            self._off = size                 # where the next chunk goes on the card
        else:
            self._writing = False
            r = sd._get(path, 0, CHUNK)
            if r["status"] == proto.FILE_NOT_A_FILE:
                raise OSError(errno.EISDIR)
            _check(r)
            self._size = r["file_size"]
            self._chunks = [(0, r["filedata"])]

    # --- reading ----------------------------------------------------------- #
    def read(self, n=-1):
        if self._writing or self.closed:
            raise OSError(errno.EBADF)
        if n is None or n < 0:
            n = self._size - self._pos
        n = max(0, min(n, self._size - self._pos))
        parts = []
        while n:
            data, i = self._chunk_at(self._pos, n)
            if not data:
                break
            # a whole chunk goes out as it came in: no copy before the final join
            take = data if i == 0 and len(data) <= n else data[i:i + n]
            parts.append(take)
            self._pos += len(take)
            n -= len(take)
        return parts[0] if len(parts) == 1 else b"".join(parts)

    def readinto(self, buf):
        data = self.read(len(buf))
        buf[:len(data)] = data
        return len(data)

    def readline(self, size=-1):
        if self._writing or self.closed:
            raise OSError(errno.EBADF)
        parts = []
        left = size if size is not None and size >= 0 else -1
        while left:
            data, k = self._chunk_at(self._pos)
            if not data:
                break
            j = data.find(b"\n", k)
            stop = len(data) if j < 0 else j + 1
            if 0 <= left < stop - k:
                stop, j = k + left, -1
            take = data[k:stop]
            parts.append(take)
            self._pos += len(take)
            if left > 0:
                left -= len(take)
            if j >= 0:
                break
        return b"".join(parts)

    def readlines(self):
        return list(self)

    def _chunk_at(self, pos, want=CHUNK):
        """(chunk, index of `pos` in it) from the chunks fetched last; when `pos` is not among
        them, fetch the chunks that hold the next `want` bytes (at most READ_AHEAD of them).
        (b"", 0) at the end of the file."""
        if pos >= self._size:
            return b"", 0
        for off, data in self._chunks:
            if off <= pos < off + len(data):
                return data, pos - off
        want = max(1, min(want, self._size - pos, READ_AHEAD * CHUNK))
        offsets = list(range(pos, pos + want, CHUNK))
        if len(offsets) > 1:
            rs = self.sd._get_many(self.path, offsets)
        else:
            rs = [self.sd._get(self.path, pos, CHUNK)]
        chunks = []
        for off, r in zip(offsets, rs):
            _check(r)
            data = r["filedata"]
            if data:
                chunks.append((off, data))
            if len(data) < CHUNK:           # the end of the file
                break
        self._chunks = chunks
        return chunks[0][1] if chunks else b"", 0

    def seek(self, offset, whence=0):
        if self._writing:
            raise OSError(errno.EINVAL)
        base = (0, self._pos, self._size)[whence]
        self._pos = max(0, base + offset)
        return self._pos

    def tell(self):
        return self._off + len(self._wbuf) if self._writing else self._pos

    # --- writing ----------------------------------------------------------- #
    def write(self, data):
        if not self._writing or self.closed:
            raise OSError(errno.EBADF)
        data = bytes(data)
        i = 0
        if self._wbuf:
            i = min(CHUNK - len(self._wbuf), len(data))
            self._wbuf += data[:i]
            if len(self._wbuf) < CHUNK:
                return len(data)
            self._put(self._wbuf)
            self._wbuf = b""
        while len(data) - i >= CHUNK:
            self._put(data[i:i + CHUNK])
            i += CHUNK
        self._wbuf = data[i:]
        return len(data)

    def flush(self):
        if self._writing and self._wbuf:
            self._put(self._wbuf)
            self._wbuf = b""

    def _put(self, chunk):
        # A retried append after a lost reply finds the file already longer: if it is
        # longer by exactly this chunk, the first attempt went through.
        for attempt in range(2):
            try:
                r = self.sd._file(proto.PUT, self.path, retry_timeout=False,
                                  offset=self._off, filedata=chunk)
            except LinkTimeout:
                if attempt:
                    raise
                continue
            if r["status"] == proto.FILE_OK or (
                    r["status"] == proto.FILE_OFFSET_CONFLICT
                    and r["file_size"] == self._off + len(chunk)):
                self._off += len(chunk)
                return
            _check(r)
            raise OSError(errno.EIO)

    # --- file object ------------------------------------------------------- #
    def close(self):
        if not self.closed:
            try:
                self.flush()
            finally:
                self.closed = True

    def ioctl(self, req, arg):
        # the stream protocol's flush (1) and close (4); seek goes through seek()
        if req == 1:
            self.flush()
            return 0
        if req == 4:
            self.close()
            return 0
        return -1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line


class _TextFile(io.IOBase):
    """UTF-8 text on top of an SDFile."""

    def __init__(self, f):
        self._f = f

    @property
    def closed(self):
        return self._f.closed

    def readinto(self, buf):
        return self._f.readinto(buf)

    def ioctl(self, req, arg):
        return self._f.ioctl(req, arg)

    def readlines(self):
        return list(self)

    def read(self, n=-1):
        data = self._f.read(n)
        return self._decode(data)

    def readline(self, size=-1):
        return self._decode(self._f.readline(size))

    def _decode(self, data):
        # a read that stopped inside a multi-byte character takes the rest of it
        for _ in range(3):
            try:
                return data.decode("utf-8")
            except UnicodeError:
                more = self._f.read(1)
                if not more:
                    break
                data += more
        return data.decode("utf-8")

    def write(self, s):
        if isinstance(s, str):
            self._f.write(s.encode("utf-8"))
            return len(s)
        return self._f.write(s)       # bytes from the stream protocol (print, json.dump)

    def seek(self, offset, whence=0):
        return self._f.seek(offset, whence)

    def tell(self):
        return self._f.tell()

    def flush(self):
        self._f.flush()

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line
