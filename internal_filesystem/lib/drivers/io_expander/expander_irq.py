# Shares a TCA9555/PCA9535 open-drain /INT line between per-pin callbacks.
#
# The expander pulls /INT low on any input change and releases it when the input port is read.
# The GPIO handler only schedules _service(); _service reads both ports once and calls the
# handlers of the pins whose level changed in the requested direction. I2C never runs in a hard
# IRQ, and a burst of edges (BUSY toggling, touch INT) collapses into one read.

import micropython


class ExpanderIRQ:
    RISING = 1   # == machine.Pin.IRQ_RISING on ESP32
    FALLING = 2  # == machine.Pin.IRQ_FALLING on ESP32

    def __init__(self, tca, int_pin, schedule=None):
        self._tca = tca
        self._schedule = schedule or micropython.schedule
        self._handlers = {}
        self._pending = False
        self._last = tca.read_inputs()
        int_pin.irq(trigger=self.FALLING, handler=self._isr)
        self._int_pin = int_pin

    def register(self, pin, handler, trigger=RISING):
        self._handlers[pin & 0x0F] = (handler, trigger)

    def unregister(self, pin):
        self._handlers.pop(pin & 0x0F, None)

    def _isr(self, _pin):
        if self._pending:
            return
        self._pending = True
        try:
            self._schedule(self._service, None)
        except RuntimeError:  # schedule queue full; the next edge or a poll() catches up
            self._pending = False

    def _service(self, _arg):
        self._pending = False
        self.poll()

    def poll(self):
        now = self._tca.read_inputs()
        changed = now ^ self._last
        self._last = now
        if changed:
            for bit, (handler, trigger) in list(self._handlers.items()):
                mask = 1 << bit
                if changed & mask:
                    rising = bool(now & mask)
                    if (rising and trigger & self.RISING) or (not rising and trigger & self.FALLING):
                        handler(bit)
        return now
