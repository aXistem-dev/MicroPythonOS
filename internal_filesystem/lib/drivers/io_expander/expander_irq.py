# Shares a TCA9555/PCA9535 open-drain /INT line between per-pin callbacks.
#
# The expander pulls /INT low on any input change and releases it when the input port is read.
# The GPIO handler only schedules _service(); _service reads both ports and calls the handlers of
# the pins whose level changed in the requested direction, re-reading while /INT is still held low.
# I2C never runs in a hard IRQ, and a burst of edges (BUSY toggling, touch INT) collapses into one
# service call. A lost edge (change before the IRQ was attached, full schedule queue) leaves /INT
# low with no further falling edge, so callers run check() periodically as a safety net.

import micropython


class ExpanderIRQ:
    RISING = 1   # == machine.Pin.IRQ_RISING on ESP32
    FALLING = 2  # == machine.Pin.IRQ_FALLING on ESP32

    _MAX_REREADS = 4

    def __init__(self, tca, int_pin, schedule=None):
        self._tca = tca
        self._schedule = schedule or micropython.schedule
        self._handlers = {}
        self._pending = False
        self._int_pin = int_pin
        int_pin.irq(trigger=self.FALLING, handler=self._isr)  # attach first, then take the baseline
        self._last = tca.read_inputs()
        self.check()

    def register(self, pin, handler, trigger=RISING):
        self._handlers[pin & 0x0F] = (handler, trigger)

    def unregister(self, pin):
        self._handlers.pop(pin & 0x0F, None)

    def pin(self, pin):
        """A machine.Pin-like view of one expander input with a working irq(), for drivers that
        attach an interrupt to a pin they are given (e.g. a radio's DIO1)."""
        return ExpanderIRQPin(self, pin)

    def _isr(self, _pin):
        if self._pending:
            return
        self._pending = True
        try:
            self._schedule(self._service, None)
        except RuntimeError:  # schedule queue full: /INT stays low, check() catches up
            self._pending = False

    def _service(self, _arg):
        self._pending = False
        for _ in range(self._MAX_REREADS):
            self.poll()
            if self._int_pin.value():
                break

    def check(self):
        """Service /INT if it is held low with nothing scheduled. Returns True if it read the ports."""
        if self._int_pin.value():
            return False
        self.poll()
        return True

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


class ExpanderIRQPin:
    """One expander input as a machine.Pin stand-in: value()/__call__ read it, irq(handler,
    trigger) attaches a handler that is called with this object, irq(None) detaches it."""

    def __init__(self, expander_irq, pin):
        self._xirq = expander_irq
        self.pin = pin & 0x0F

    def init(self, *args, **kwargs):
        pass  # an expander input; its direction is set where the expander is configured

    def value(self, v=None):
        if v is not None:
            raise OSError(1)  # an input
        return 1 if self._xirq._tca.read_inputs() & (1 << self.pin) else 0

    def __call__(self, v=None):
        return self.value(v)

    def irq(self, handler=None, trigger=ExpanderIRQ.RISING, **kwargs):
        if handler is None:
            self._xirq.unregister(self.pin)
        else:
            self._xirq.register(self.pin, lambda _bit: handler(self), trigger)
