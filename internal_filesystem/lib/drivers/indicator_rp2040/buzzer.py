# The buzzer on the RP2040 as a PWM-like object (freq, duty_u16, deinit), which is what
# MicroPythonOS's RTTTL player drives. The RP2040 sounds a fixed-loudness tone, so the duty
# cycle only switches it on (> 0) or off (0); a tone is sent when that, or the pitch, changes.

class RemoteBuzzer:

    def __init__(self, link):
        self.link = link
        self._freq = 1000
        self._on = False

    def freq(self, value=None):
        if value is None:
            return self._freq
        value = int(value)
        if value != self._freq:
            self._freq = value
            if self._on:
                self._tone(value)

    def duty_u16(self, value=None):
        if value is None:
            return 32768 if self._on else 0
        on = value > 0
        if on != self._on:
            self._on = on
            self._tone(self._freq if on else 0)

    def duty(self, value=None):
        if value is None:
            return 512 if self._on else 0
        self.duty_u16(value * 64)

    def deinit(self):
        self._on = False
        self._tone(0)

    def beep(self, duration_ms):
        """The RP2040's own short beep (its fixed pitch)."""
        self.link.send({"beep": int(duration_ms)})

    def _tone(self, frequency):
        self.link.send({"tone": {"frequency_hz": frequency, "duration_ms": 0}})
