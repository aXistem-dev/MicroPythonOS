import sys
import unittest

from mpos.testing.mocks import MockMachine, create_mock_module, inject_mocks


class FakeDevice:
    """i2c.I2C.Device stand-in holding a PCA9535 register file (power-on: OUT 0xFFFF, CFG 0xFFFF)."""

    def __init__(self, bus, dev_id, **kw):
        self.regs = bytearray([0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0xFF, 0xFF])
        self.writes = []
        self._ptr = 0

    def write(self, data):
        self._ptr = data[0]
        if len(data) > 1:
            self.regs[self._ptr:self._ptr + len(data) - 1] = data[1:]
            self.writes.append((self._ptr, bytes(data[1:])))

    def read(self, n):
        return bytes(self.regs[self._ptr:self._ptr + n])


class FakeIntPin:
    """Expander /INT line: open-drain, active low. `levels` is consumed by value() calls, then `level`."""

    def __init__(self, level=1, levels=None, log=None):
        self.handler = None
        self.trigger = None
        self.level = level
        self.levels = list(levels or [])
        self.log = log

    def irq(self, trigger=None, handler=None):
        self.trigger, self.handler = trigger, handler
        if self.log is not None:
            self.log.append("irq")

    def value(self):
        return self.levels.pop(0) if self.levels else self.level


inject_mocks({
    "machine": MockMachine(),
    "i2c": create_mock_module("i2c", I2C=create_mock_module("I2C", Device=FakeDevice, Bus=object)),
})
for name in ("drivers.io_expander.tca9555", "drivers.io_expander.expander_irq"):
    sys.modules.pop(name, None)
from drivers.io_expander.tca9555 import TCA9555, ExpanderPin  # noqa: E402
from drivers.io_expander.expander_irq import ExpanderIRQ  # noqa: E402

OUT = MockMachine.Pin.OUT
IN = MockMachine.Pin.IN


def make():
    tca = TCA9555(object(), dev_id=0x20)
    dev = tca.tca_dev
    dev.writes.clear()
    return tca, dev


class TestExpanderPin(unittest.TestCase):
    def test_read_inputs_does_not_touch_config(self):
        tca, dev = make()
        dev.regs[0], dev.regs[1] = 0x04, 0x08
        self.assertEqual(tca.read_inputs(), 0x0804)
        self.assertEqual(dev.writes, [])

    def test_output_init_writes_level_before_direction(self):
        tca, dev = make()
        ExpanderPin(tca, 4, OUT, value=1)
        self.assertEqual(dev.writes[0][0], 0x02)          # OUTPUT first
        self.assertEqual(dev.writes[-1][0], 0x06)         # then CONFIG
        self.assertEqual(dev.regs[6] & 0x10, 0)           # P0.4 is now an output
        self.assertEqual(dev.regs[2] & 0x10, 0x10)        # driven high

    def test_input_read_uses_input_register(self):
        tca, dev = make()
        tcxo = ExpanderPin(tca, 0x40 | 11, IN)
        dev.writes.clear()
        dev.regs[1] = 0x08
        self.assertEqual(tcxo(), 1)
        dev.regs[1] = 0x00
        self.assertEqual(tcxo.value(), 0)
        self.assertEqual(dev.writes, [])                  # no CONFIG rewrite on read
        self.assertEqual(tcxo.pin, 11)

    def test_drive_low_high(self):
        tca, dev = make()
        nss = ExpanderPin(tca, 0)
        nss.init(OUT, value=1)
        nss(0)
        self.assertEqual(dev.regs[2] & 0x01, 0)
        nss(1)
        self.assertEqual(dev.regs[2] & 0x01, 1)


class TestExpanderIRQ(unittest.TestCase):
    def setUp(self):
        self.tca, self.dev = make()
        self.int_pin = FakeIntPin()
        self.irq = ExpanderIRQ(self.tca, self.int_pin)
        self.calls = []

    def test_hooks_falling_edge_on_int_pin(self):
        self.assertEqual(self.int_pin.trigger, ExpanderIRQ.FALLING)
        self.assertIsNotNone(self.int_pin.handler)

    def test_rising_handler_only_on_rising_change(self):
        self.irq.register(3, self.calls.append)               # DIO1, rising
        self.dev.regs[0] = 0x08
        self.irq.poll()
        self.dev.regs[0] = 0x00
        self.irq.poll()
        self.assertEqual(self.calls, [3])

    def test_unchanged_pins_do_not_fire(self):
        self.irq.register(3, self.calls.append)
        self.dev.regs[0] = 0x04                                # only BUSY (bit 2) toggles
        self.irq.poll()
        self.assertEqual(self.calls, [])

    def test_falling_trigger_and_port1_bits(self):
        self.dev.regs[1] = 0x08
        self.irq.poll()                                        # establish high
        self.irq.register(0x40 | 11, self.calls.append, ExpanderIRQ.FALLING)
        self.dev.regs[1] = 0x00
        self.irq.poll()
        self.assertEqual(self.calls, [11])

    def test_isr_coalesces_into_one_scheduled_service(self):
        scheduled = []
        int_pin = FakeIntPin()
        ExpanderIRQ(self.tca, int_pin, schedule=lambda f, a: scheduled.append((f, a)))
        int_pin.handler(int_pin)
        int_pin.handler(int_pin)
        self.assertEqual(len(scheduled), 1)
        f, a = scheduled[0]
        f(a)
        int_pin.handler(int_pin)
        self.assertEqual(len(scheduled), 2)

    def test_irq_attached_before_baseline_read(self):
        log = []
        reads = []
        orig = self.tca.read_inputs
        self.tca.read_inputs = lambda: (log.append("read"), orig())[1]
        ExpanderIRQ(self.tca, FakeIntPin(log=log), schedule=lambda f, a: None)
        self.assertEqual(log[0], "irq")

    def test_service_rereads_while_int_held_low(self):
        int_pin = FakeIntPin()
        scheduled = []
        irq = ExpanderIRQ(self.tca, int_pin, schedule=lambda f, a: scheduled.append((f, a)))
        irq.register(3, self.calls.append)
        reads = []
        orig = self.tca.read_inputs
        self.tca.read_inputs = lambda: (reads.append(1), orig())[1]
        int_pin.levels = [0, 1]              # still low after the first read, released after the second
        self.dev.regs[0] = 0x08
        int_pin.handler(int_pin)
        f, a = scheduled[0]
        f(a)
        self.assertEqual(len(reads), 2)
        self.assertEqual(self.calls, [3])

    def test_check_reads_only_when_int_low(self):
        int_pin = FakeIntPin()
        irq = ExpanderIRQ(self.tca, int_pin, schedule=lambda f, a: None)
        irq.register(3, self.calls.append)
        reads = []
        orig = self.tca.read_inputs
        self.tca.read_inputs = lambda: (reads.append(1), orig())[1]
        self.assertFalse(irq.check())
        self.assertEqual(reads, [])
        int_pin.level = 0
        self.dev.regs[0] = 0x08
        self.assertTrue(irq.check())
        self.assertEqual(self.calls, [3])

    def test_full_schedule_queue_is_recovered_by_check(self):
        def full(f, a):
            raise RuntimeError("schedule queue full")
        int_pin = FakeIntPin()
        irq = ExpanderIRQ(self.tca, int_pin, schedule=full)
        irq.register(3, self.calls.append)
        self.dev.regs[0] = 0x08
        int_pin.level = 0
        int_pin.handler(int_pin)             # edge lost: queue full
        self.assertEqual(self.calls, [])
        irq.check()                          # the periodic safety net
        self.assertEqual(self.calls, [3])

    def test_unregister(self):
        self.irq.register(3, self.calls.append)
        self.irq.unregister(3)
        self.dev.regs[0] = 0x08
        self.irq.poll()
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
