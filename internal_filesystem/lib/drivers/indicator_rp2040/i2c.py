# The Grove I2C port, which hangs off the RP2040, as a machine.I2C-compatible object: sensor
# drivers written for machine.I2C (scan, readfrom_mem, writeto, ...) work unchanged. Each call
# is one transaction on the RP2040: an optional write, then an optional read with a repeated
# start. A write with stop=False is held back and joined to the read that follows it.

import errno

from . import proto

MAX_DATA = 256       # write_data / read_data limit of one transaction


class RemoteI2C:

    def __init__(self, link):
        self.link = link
        self._pending = None          # (addr, bytes) written with stop=False

    def scan(self):
        self._flush()
        return list(self.link.request({"i2c_scan": True})["i2c_scan_result"])

    # --- primitives -------------------------------------------------------- #
    def readfrom(self, addr, nbytes, stop=True):
        return self._transaction(addr, self._take_pending(addr), nbytes)

    def readfrom_into(self, addr, buf, stop=True):
        data = self.readfrom(addr, len(buf), stop)
        buf[:len(data)] = data

    def writeto(self, addr, buf, stop=True):
        self._flush()
        if not stop:
            self._pending = (addr, bytes(buf))
            return len(buf)
        self._transaction(addr, bytes(buf), 0)
        return len(buf)

    def writevto(self, addr, vector, stop=True):
        return self.writeto(addr, b"".join(bytes(v) for v in vector), stop)

    # --- register access --------------------------------------------------- #
    def readfrom_mem(self, addr, memaddr, nbytes, addrsize=8):
        self._flush()
        return self._transaction(addr, _memaddr(memaddr, addrsize), nbytes)

    def readfrom_mem_into(self, addr, memaddr, buf, addrsize=8):
        data = self.readfrom_mem(addr, memaddr, len(buf), addrsize)
        buf[:len(data)] = data

    def writeto_mem(self, addr, memaddr, buf, addrsize=8):
        self._flush()
        self._transaction(addr, _memaddr(memaddr, addrsize) + bytes(buf), 0)

    # --- internals ----------------------------------------------------------- #
    def _take_pending(self, addr):
        p, self._pending = self._pending, None
        if p is None:
            return b""
        if p[0] != addr:
            self._transaction(p[0], p[1], 0)
            return b""
        return p[1]

    def _flush(self):
        p, self._pending = self._pending, None
        if p is not None:
            self._transaction(p[0], p[1], 0)

    def _transaction(self, addr, write, nbytes):
        if nbytes > MAX_DATA or len(write) > MAX_DATA:
            raise ValueError("at most %d bytes per I2C transfer" % MAX_DATA)
        r = self.link.request({"i2c_transaction": {"address": addr, "write_data": write,
                                                   "read_len": nbytes}})["i2c_result"]
        status = r["status"]
        if status == proto.I2C_NACK_ADDRESS:
            raise OSError(errno.ENODEV)          # what machine.I2C raises for no device
        if status != proto.I2C_OK:
            raise OSError(errno.EIO)
        return r["read_data"]


def _memaddr(memaddr, addrsize):
    if addrsize == 8:
        return bytes((memaddr & 0xFF,))
    if addrsize == 16:
        return bytes(((memaddr >> 8) & 0xFF, memaddr & 0xFF))
    raise ValueError("addrsize must be 8 or 16")
