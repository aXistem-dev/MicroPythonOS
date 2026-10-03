# The SD card in the RP2040's slot as a MicroPython VFS: os.mount(SDCard(link), "/sd") and the
# usual open()/os.listdir()/os.stat() work on it. Reads are ranged 4 KB GETs with a one-chunk
# cache (map tiles are read front to back); writes are buffered into 4 KB appends.

import errno
import time

from . import proto
from .link import LinkTimeout

CHUNK = 4096
_DIR, _FILE = 0x4000, 0x8000

# MicroPython's errno module leaves these out; the POSIX values
EBUSY = getattr(errno, "EBUSY", 16)
ENOTDIR = getattr(errno, "ENOTDIR", 20)

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
        """proto.SD_MOUNT / SD_EJECT / SD_FORMAT; returns the card info afterwards."""
        return self.link.request({"sd_command": cmd}, timeout_ms=30000)["sd_info"]

    def format(self):
        """Wipe the card and put a fresh FAT on it (the RP2040 does it). True when mounted after."""
        return bool(self.command(proto.SD_FORMAT)["present"])

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
        raise OSError(errno.EPERM)       # not offered by the RP2040 firmware

    def rename(self, old, new):
        raise OSError(errno.EPERM)       # not offered by the RP2040 firmware

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
        return "/" + "/".join(parts)

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


class SDFile:
    """A binary file on the card. Modes: r, w, a (with or without b)."""

    def __init__(self, sd, path, mode):
        self.sd = sd
        self.path = path
        self.closed = False
        self._pos = 0
        self._cache_off = 0
        self._cache = b""
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
            self._cache = r["filedata"]

    # --- reading ----------------------------------------------------------- #
    def read(self, n=-1):
        if self._writing:
            raise OSError(errno.EBADF)
        if n is None or n < 0:
            n = self._size - self._pos
        n = max(0, min(n, self._size - self._pos))
        parts = []
        while n:
            data = self._chunk_at(self._pos)
            if not data:
                break
            take = data[:n]
            parts.append(take)
            self._pos += len(take)
            n -= len(take)
        return b"".join(parts)

    def readinto(self, buf):
        data = self.read(len(buf))
        buf[:len(data)] = data
        return len(data)

    def readline(self):
        parts = []
        while True:
            data = self._chunk_at(self._pos)
            if not data:
                break
            i = data.find(b"\n")
            take = data if i < 0 else data[:i + 1]
            parts.append(take)
            self._pos += len(take)
            if i >= 0:
                break
        return b"".join(parts)

    def _chunk_at(self, pos):
        """The cached bytes from `pos` on, fetching the chunk that holds `pos` if needed."""
        if pos >= self._size:
            return b""
        end = self._cache_off + len(self._cache)
        if not (self._cache_off <= pos < end):
            r = self.sd._get(self.path, pos, CHUNK)
            _check(r)
            self._cache_off, self._cache = pos, r["filedata"]
            if not self._cache:
                return b""
        return self._cache[pos - self._cache_off:]

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
        if not self._writing:
            raise OSError(errno.EBADF)
        self._wbuf += bytes(data)
        while len(self._wbuf) >= CHUNK:
            self._put(self._wbuf[:CHUNK])
            self._wbuf = self._wbuf[CHUNK:]
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


class _TextFile:
    """UTF-8 text on top of an SDFile."""

    def __init__(self, f):
        self._f = f

    def read(self, n=-1):
        data = self._f.read(n)
        return self._decode(data)

    def readline(self):
        return self._decode(self._f.readline())

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
        return self._f.write(s.encode("utf-8"))

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
