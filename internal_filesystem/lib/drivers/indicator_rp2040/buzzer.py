# The buzzer on the RP2040 as a PWM-like object (freq, duty_u16, deinit), which is what
# MicroPythonOS's RTTTL player drives. The RP2040 sounds a fixed-loudness tone, so the duty
# cycle only switches it on (> 0) or off (0); a tone is sent when that, or the pitch, changes.
#
# Firmware without the tone message (it nacks it) still has its fixed-pitch beep: the buzzer
# then keeps the rhythm of a tune at that one pitch. reset() finds out which one is there.

# Every sound ends on its own after this long, so a lost "off" (the ESP32 reset mid-tune, a
# request that failed) cannot leave the buzzer sounding. Longer than any RTTTL note.
MAX_SOUND_MS = 5000


def reset(link):
    """Silence a sound left on from before, and learn whether the firmware plays tones: the
    ping behind the tone comes back after the RP2040's nack of it, if any."""
    link.send({"tone": {"frequency_hz": 0}})
    link.ping()
    if "tone" in link.refused:
        link.send({"beep": 0})


class RemoteBuzzer:

    def __init__(self, link):
        self.link = link
        self._freq = 1000
        self._on = False
        self._closed = False

    def freq(self, value=None):
        if value is None:
            return self._freq
        self._check()
        value = int(value)
        if value != self._freq:
            if self._on:
                self._sound(value)
            self._freq = value

    def duty_u16(self, value=None):
        if value is None:
            return 32768 if self._on else 0
        self._check()
        on = value > 0
        if on != self._on:
            self._sound(self._freq if on else 0)
            self._on = on

    def duty(self, value=None):
        if value is None:
            return 512 if self._on else 0
        self.duty_u16(value * 64)

    def deinit(self):
        # like machine.PWM: later calls raise RuntimeError, which the RTTTL player expects
        # when another tune took over
        if self._closed:
            return
        self._closed = True
        if self._on:
            self._on = False
            try:
                self._sound(0)
            except OSError:
                pass            # the sound still ends after MAX_SOUND_MS

    def beep(self, duration_ms):
        """The RP2040's own short beep (its fixed pitch)."""
        self.link.send({"beep": max(0, min(int(duration_ms), 65535))})   # the firmware's 16-bit field

    def _check(self):
        if self._closed:
            raise RuntimeError("buzzer deinitialized")

    def _sound(self, frequency):
        if "tone" in self.link.refused:
            self.link.send({"beep": MAX_SOUND_MS if frequency else 0})
        else:
            self.link.send({"tone": {"frequency_hz": frequency,
                                     "duration_ms": MAX_SOUND_MS if frequency else 0}})
