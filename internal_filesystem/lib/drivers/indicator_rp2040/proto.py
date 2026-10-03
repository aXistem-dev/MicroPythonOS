# InterdeviceMessage codec for the SenseCAP Indicator's RP2040 (Meshtastic indicator_rp2040
# firmware, interdevice.proto). Hand-written protobuf: the messages are small and fixed, and a
# generated runtime would cost more flash than this table.
#
# Messages are dicts keyed by the .proto field names. A request holds "id" and the one `data`
# member it carries; a decoded message always has "id" (0 when absent), and sub-messages come
# back with every field, defaults included. Enums are plain ints (constants below).

MAGIC = b"\x94\xc3"
HEADER_SIZE = 4

INTERDEVICE_VERSION = 2

# FileOperation
GET, POST, PUT, DELETE, MKDIR = 0, 1, 2, 3, 4
# FileStatus
FILE_UNSPECIFIED, FILE_OK, FILE_BUSY, FILE_NO_CARD, FILE_NOT_FOUND, FILE_OFFSET_CONFLICT, \
    FILE_IO_ERROR, FILE_NOT_A_FILE = range(8)
# I2CResult.Status
I2C_UNSPECIFIED, I2C_OK, I2C_NACK_ADDRESS, I2C_NACK_DATA, I2C_ERROR = range(5)
# SdCommand
SD_MOUNT, SD_EJECT, SD_FORMAT = 1, 2, 3

_V, _B, _S, _M, _RS = "v", "b", "s", "m", "rs"   # varint, bytes, string, message, repeated string

_SCHEMAS = {
    "FileTransfer": ((1, "operation", _V), (2, "filepath", _S), (3, "filedata", _B),
                     (4, "status", _V), (5, "message", _S), (6, "offset", _V),
                     (7, "length", _V), (8, "file_size", _V)),
    "DirectoryListing": ((1, "directory", _S), (2, "filenames", _RS), (3, "status", _V),
                         (4, "message", _S), (5, "offset", _V), (6, "total_count", _V)),
    "I2CTransaction": ((1, "address", _V), (2, "write_data", _B), (3, "read_len", _V)),
    "I2CResult": ((1, "status", _V), (2, "read_data", _B)),
    "SdCardInfo": ((1, "present", _V), (2, "card_type", _V), (3, "fat_type", _V),
                   (4, "card_size", _V), (5, "used_bytes", _V), (6, "free_bytes", _V),
                   (7, "stats_valid", _V), (8, "busy", _V), (9, "unformatted", _V)),
    "BuzzerTone": ((1, "frequency_hz", _V), (2, "duration_ms", _V)),
}
_BOOLS = ("present", "stats_valid", "busy", "unformatted", "i2c_scan", "get_sd_info", "nack")

# InterdeviceMessage, in field-number order (the order the official encoders write)
_TOP = ((1, "nmea", _S), (2, "beep", _V), (3, "i2c_transaction", "I2CTransaction"),
        (4, "i2c_result", "I2CResult"), (5, "i2c_scan", _V), (6, "i2c_scan_result", _B),
        (7, "file_transfer", "FileTransfer"), (8, "directory_listing", "DirectoryListing"),
        (9, "get_sd_info", _V), (10, "sd_info", "SdCardInfo"), (11, "ping", _V),
        (12, "pong", _V), (13, "nack", _V), (14, "sd_command", _V), (15, "id", _V),
        (16, "tone", "BuzzerTone"))
_TOP_BY_NUM = {n: (name, kind) for n, name, kind in _TOP}


# --- wire primitives ------------------------------------------------------- #

def _varint(n, out):
    n = int(n)
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def _key(num, wire, out):
    _varint((num << 3) | wire, out)


def _read_varint(buf, i):
    n = 0
    shift = 0
    while True:
        if i >= len(buf):
            raise ValueError("truncated varint")
        b = buf[i]
        i += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, i
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _read_len(buf, i):
    n, i = _read_varint(buf, i)
    if i + n > len(buf):
        raise ValueError("truncated field")
    return i, i + n


def _fields(buf):
    """Yield (field number, wire type, value) where value is an int (varint) or a
    memoryview slice (length-delimited); fixed32/64 fields are skipped."""
    i = 0
    end = len(buf)
    while i < end:
        key, i = _read_varint(buf, i)
        num, wire = key >> 3, key & 7
        if wire == 0:
            v, i = _read_varint(buf, i)
            yield num, wire, v
        elif wire == 2:
            a, i = _read_len(buf, i)
            yield num, wire, buf[a:i]
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            raise ValueError("unsupported wire type %d" % wire)
        if i > end:
            raise ValueError("truncated field")


# --- encode -------------------------------------------------------------- #

def _put(num, kind, value, out, always):
    if kind == _V:
        v = int(value)
        if v or always:
            _key(num, 0, out)
            _varint(v, out)
    elif kind in (_B, _S):
        data = value.encode("utf-8") if kind == _S and isinstance(value, str) else bytes(value)
        if data or always:
            _key(num, 2, out)
            _varint(len(data), out)
            out.extend(data)
    elif kind == _RS:
        for s in value:
            _put(num, _S, s, out, True)
    else:
        sub = _encode_message(kind, value)
        _key(num, 2, out)
        _varint(len(sub), out)
        out.extend(sub)


def _encode_message(schema, d):
    out = bytearray()
    for num, name, kind in _SCHEMAS[schema]:
        if name in d:
            _put(num, kind, d[name], out, False)
    return out


def encode(msg):
    """InterdeviceMessage dict -> protobuf bytes. The oneof member is written even when it
    holds its default value (a `beep` of 0 still says "stop beeping")."""
    out = bytearray()
    for num, name, kind in _TOP:
        if name in msg:
            _put(num, kind, msg[name], out, name != "id")
    return bytes(out)


# --- decode -------------------------------------------------------------- #

def _defaults(schema):
    d = {}
    for _, name, kind in _SCHEMAS[schema]:
        if kind == _V:
            d[name] = False if name in _BOOLS else 0
        elif kind == _B:
            d[name] = b""
        elif kind == _S:
            d[name] = ""
        else:
            d[name] = []
    return d


def _value(name, kind, wire, v):
    if kind == _V:
        if wire != 0:
            raise ValueError("%s: expected a varint" % name)
        return bool(v) if name in _BOOLS else v
    if wire != 2:
        raise ValueError("%s: expected a length-delimited field" % name)
    if kind == _S:
        return bytes(v).decode("utf-8")
    if kind == _B:
        return bytes(v)
    return _decode_message(kind, v)


def _decode_message(schema, buf):
    d = _defaults(schema)
    by_num = {n: (name, kind) for n, name, kind in _SCHEMAS[schema]}
    for num, wire, v in _fields(buf):
        f = by_num.get(num)
        if f is None:
            continue
        name, kind = f
        if kind == _RS:
            d[name].append(_value(name, _S, wire, v))
        else:
            d[name] = _value(name, kind, wire, v)
    return d


def decode(payload):
    """Protobuf bytes -> InterdeviceMessage dict ({"id": n, member: value}). Raises
    ValueError on a malformed payload. Unknown fields are skipped; when several oneof
    members are present the last one wins, as in protobuf."""
    buf = memoryview(payload)
    msg = {"id": 0}
    member = None
    for num, wire, v in _fields(buf):
        f = _TOP_BY_NUM.get(num)
        if f is None:
            continue
        name, kind = f
        value = _value(name, kind, wire, v)
        if name == "id":
            msg["id"] = value
            continue
        if member is not None:
            del msg[member]
        member = name
        msg[name] = value
    return msg


def frame(payload):
    """Wire frame: magic, big-endian 16-bit payload length, payload."""
    n = len(payload)
    if n > 0xFFFF:
        raise ValueError("payload too large")
    return MAGIC + bytes((n >> 8, n & 0xFF)) + payload
