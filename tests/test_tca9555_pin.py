import sys
import unittest

from mpos.testing.mocks import MockMachine, create_mock_module, inject_mocks


class FakeDevice:
    """i2c.I2C.Device stand-in holding a TCA9555/PCA9535 register file (power-on: OUT 0xFFFF, CFG 0xFFFF)."""

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


inject_mocks({
    "machine": MockMachine(),
    "i2c": create_mock_module("i2c", I2C=create_mock_module("I2C", Device=FakeDevice, Bus=object)),
})
sys.modules.pop("drivers.io_expander.tca9555", None)
from drivers.io_expander.tca9555 import TCA9555, TCA9555Pin  # noqa: E402

OUT = MockMachine.Pin.OUT
IN = MockMachine.Pin.IN
REG_OUTPUT = 0x02
REG_CONFIG = 0x06


def make():
    tca = TCA9555(object(), dev_id=0x20)
    dev = tca.tca_dev
    dev.writes.clear()
    return tca, dev


class TestReadInputs(unittest.TestCase):
    def test_reads_both_ports_without_touching_config(self):
        tca, dev = make()
        dev.regs[0], dev.regs[1] = 0x04, 0x08
        self.assertEqual(tca.read_inputs(), 0x0804)
        self.assertEqual(dev.writes, [])


class TestTCA9555Pin(unittest.TestCase):
    def test_output_with_initial_value_writes_level_before_direction(self):
        tca, dev = make()
        TCA9555Pin(tca, 0x40 | 4, OUT, value=1)
        self.assertEqual(dev.writes[0][0], REG_OUTPUT)
        self.assertEqual(dev.writes[-1][0], REG_CONFIG)
        self.assertEqual(dev.regs[REG_OUTPUT] & 0x10, 0x10)
        self.assertEqual(dev.regs[REG_CONFIG] & 0x10, 0)

    def test_output_with_initial_low_value(self):
        tca, dev = make()
        TCA9555Pin(tca, 0x40 | 9, OUT, value=0)
        self.assertEqual(dev.regs[REG_OUTPUT + 1] & 0x02, 0)
        self.assertEqual(dev.regs[REG_CONFIG + 1] & 0x02, 0)

    def test_output_without_initial_value_keeps_previous_behaviour(self):
        tca, dev = make()
        TCA9555Pin(tca, 0x40 | 4)
        self.assertEqual([reg for reg, _ in dev.writes], [REG_CONFIG])

    def test_input_pin_reads_the_input_register(self):
        tca, dev = make()
        pin = TCA9555Pin(tca, 0x40 | 11, IN)
        dev.writes.clear()
        dev.regs[1] = 0x08
        self.assertEqual(pin.value(), 1)
        dev.regs[1] = 0x00
        self.assertEqual(pin(), 0)
        self.assertEqual(dev.writes, [])

    def test_reading_never_turns_an_output_into_an_input(self):
        tca, dev = make()
        pin = TCA9555Pin(tca, 0x40 | 2, OUT, value=1)
        pin.value()
        self.assertEqual(dev.regs[REG_CONFIG] & 0x04, 0)

    def test_write(self):
        tca, dev = make()
        pin = TCA9555Pin(tca, 0x40 | 5, OUT, value=1)
        pin(0)
        self.assertEqual(dev.regs[REG_OUTPUT] & 0x20, 0)
        pin.value(1)
        self.assertEqual(dev.regs[REG_OUTPUT] & 0x20, 0x20)

    def test_init_reconfigures_like_machine_pin(self):
        # Drivers written for machine.Pin call pin.init(Pin.OUT, value=0) on reset lines
        tca, dev = make()
        pin = TCA9555Pin(tca, 0x40 | 1, IN)
        self.assertEqual(dev.regs[REG_CONFIG] & 0x02, 0x02)
        pin.init(OUT, value=0)
        self.assertEqual(dev.regs[REG_CONFIG] & 0x02, 0)
        self.assertEqual(dev.regs[REG_OUTPUT] & 0x02, 0)
        pin.init(IN)
        self.assertEqual(dev.regs[REG_CONFIG] & 0x02, 0x02)


if __name__ == "__main__":
    unittest.main()
