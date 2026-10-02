import sys
import unittest

from mpos.testing.mocks import MockMachine, inject_mocks

inject_mocks({"machine": MockMachine()})
sys.modules.pop("drivers.display.st7701s.hybrid_spi3wire", None)
from drivers.display.st7701s.hybrid_spi3wire import HybridSpi3Wire  # noqa: E402


class Line:
    def __init__(self, name, log):
        self.name, self.log, self.v = name, log, None
        self.mode = None

    def init(self, mode, value=None):
        self.mode = mode
        if value is not None:
            self(value)

    def __call__(self, v=None):
        if v is None:
            return self.v
        self.v = v
        self.log.append((self.name, v))

    value = __call__


def sampled_words(log):
    """Reassemble 9-bit words from data levels at each rising clock edge, per CS-low frame."""
    frames, bits, clk, mosi, cs = [], [], 0, 0, 1
    for name, v in log:
        if name == "cs":
            if v == 0:
                bits = []
            elif cs == 0:
                frames.append([int("".join(map(str, bits[i:i + 9])), 2) for i in range(0, len(bits), 9)])
            cs = v
        elif name == "mosi":
            mosi = v
        elif name == "clk":
            if v == 1 and clk == 0 and cs == 0:
                bits.append(mosi)
            clk = v
    return frames


class TestHybridSpi3Wire(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.cs, self.clk, self.mosi = Line("cs", self.log), Line("clk", self.log), Line("mosi", self.log)
        self.spi = HybridSpi3Wire(self.cs, self.clk, self.mosi)
        self.spi.init(8, 8)

    def test_idle_state_after_init(self):
        self.assertEqual((self.cs.v, self.clk.v), (1, 0))

    def test_command_with_params_as_9bit_words(self):
        self.log.clear()
        self.spi.tx_param(0xFF, [0x77, 0x01])
        self.assertEqual(sampled_words(self.log), [[0x0FF, 0x177, 0x101]])
        self.assertEqual(self.cs.v, 1)

    def test_command_without_params(self):
        self.log.clear()
        self.spi.tx_param(0x29)
        self.assertEqual(sampled_words(self.log), [[0x029]])

    def test_deinit_releases_gpio(self):
        self.spi.deinit()
        self.assertEqual(self.clk.mode, MockMachine.Pin.IN)
        self.assertEqual(self.mosi.mode, MockMachine.Pin.IN)


if __name__ == "__main__":
    unittest.main()
