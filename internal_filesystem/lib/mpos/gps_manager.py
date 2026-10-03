class GPSManager:
    """Where GPS data comes from and who wants it.

    A board registers an NMEA source: an object with an `on_nmea` hook it calls with each
    sentence, and a `poll()` that brings in what arrived (for example a GPS module on a
    co-processor's serial port, forwarded over the inter-chip link). Apps add listeners and
    call poll() now and then; position_from_nmea() reads a fix out of a sentence."""

    txPin = None
    rxPin = None
    connectionType = None
    connectionSpeed = None

    _source = None
    _listeners = []

    @classmethod
    def set_nmea_source(cls, source):
        if cls._source is not None:
            cls._source.on_nmea = None
        cls._source = source
        if source is not None:
            source.on_nmea = cls._dispatch

    @classmethod
    def has_nmea_source(cls):
        return cls._source is not None

    @classmethod
    def add_nmea_listener(cls, callback):
        if callback not in cls._listeners:
            cls._listeners.append(callback)

    @classmethod
    def remove_nmea_listener(cls, callback):
        try:
            cls._listeners.remove(callback)
        except ValueError:
            pass

    @classmethod
    def poll(cls):
        """Bring in the sentences that arrived; False without a working source."""
        src = cls._source
        if src is None:
            return False
        try:
            src.poll()
            return True
        except Exception:
            return False

    @classmethod
    def _dispatch(cls, sentence):
        for cb in list(cls._listeners):
            try:
                cb(sentence)
            except Exception as e:
                print("GPSManager: NMEA listener error:", repr(e))

    @staticmethod
    def position_from_nmea(sentence):
        """(lat, lon) in degrees from an RMC or GGA sentence with a fix, else None. A
        sentence with a checksum must match it."""
        try:
            s = sentence.strip()
            if not s.startswith("$"):
                return None
            body = s[1:]
            star = body.find("*")
            if star >= 0:
                c = 0
                for ch in body[:star]:
                    c ^= ord(ch)
                if int(body[star + 1:star + 3], 16) != c:
                    return None
                body = body[:star]
            f = body.split(",")
            kind = f[0][2:]
            if kind == "RMC" and len(f) > 6 and f[2] == "A":
                lat, ns, lon, ew = f[3], f[4], f[5], f[6]
            elif kind == "GGA" and len(f) > 6 and f[6] not in ("", "0"):
                lat, ns, lon, ew = f[2], f[3], f[4], f[5]
            else:
                return None
            la = int(float(lat) / 100)
            lo = int(float(lon) / 100)
            lat_d = la + (float(lat) - la * 100) / 60
            lon_d = lo + (float(lon) - lo * 100) / 60
            if ns == "S":
                lat_d = -lat_d
            if ew == "W":
                lon_d = -lon_d
            return lat_d, lon_d
        except (ValueError, IndexError):
            return None
