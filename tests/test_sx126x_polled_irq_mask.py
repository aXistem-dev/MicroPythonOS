import sys
import unittest

from mpos.testing.mocks import MockMachine, inject_mocks

class _Pin(MockMachine.Pin):
    IRQ_RISING = 1
    IRQ_FALLING = 2


class _Machine(MockMachine):
    Pin = _Pin


inject_mocks({"machine": _Machine()})
for m in ("lora", "lora.sx126x", "lora.modem", "lora.sync_modem"):
    sys.modules.pop(m, None)
from lora import SX1262  # noqa: E402


class FakeSPI:
    """Answers like an idle SX1262: status 0x22 (STDBY_RC) in the byte after the opcode, zeros
    after it (no device errors, no IRQ flags)."""

    def __init__(self):
        self.frames = []

    def write_readinto(self, wr, rd):
        self.frames.append(bytes(wr))
        for i in range(len(rd)):
            rd[i] = 0x22 if i == 1 else 0

    def write(self, wr):
        self.frames.append(bytes(wr))

    def readinto(self, buf, fill=0):
        for i in range(len(buf)):
            buf[i] = 0


class Line:
    def __init__(self, v=0):
        self.v = v

    def init(self, *a, **k):
        if "value" in k and k["value"] is not None:
            self.v = k["value"]

    def __call__(self, v=None):
        if v is None:
            return self.v
        self.v = v

    value = __call__


def cfg_dio_irq_frames(spi):
    return [f for f in spi.frames if f and f[0] == 0x08]


class TestPolledIrqMask(unittest.TestCase):
    def make(self, dio1):
        spi = FakeSPI()
        SX1262(spi=spi, cs=Line(1), busy=Line(0), dio1=dio1, dio2_rf_sw=True,
               dio3_tcxo_millivolts=None, reset=None)
        return spi

    def test_polled_radio_still_gets_an_irq_mask(self):
        frames = cfg_dio_irq_frames(self.make(dio1=None))
        self.assertTrue(frames, "no SetDioIrqParams sent without dio1")
        f = frames[-1]
        self.assertEqual((f[1] << 8) | f[2], 0x0257)   # IrqMask, incl. PREAMBLE_DETECTED and HEADER_VALID
        self.assertEqual((f[3] << 8) | f[4], 0x0000)   # DIO1 mask: nothing routed

    def test_dio1_mask_unchanged_when_pin_given(self):
        class Dio1(Line):
            def irq(self, handler, trigger):
                self.handler = handler
        frames = cfg_dio_irq_frames(self.make(dio1=Dio1()))
        f = frames[-1]
        self.assertEqual((f[1] << 8) | f[2], 0x0257)
        self.assertEqual((f[3] << 8) | f[4], 0x0203)


if __name__ == "__main__":
    unittest.main()
