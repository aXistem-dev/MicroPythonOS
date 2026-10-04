import unittest

from mpos.board import sensecap_indicator_probe as probe


class FakeI2C:
    def __init__(self, present):
        self.present = present

    def writeto(self, addr, buf):
        if addr not in self.present:
            raise OSError(19)


class TestProbe(unittest.TestCase):
    def test_expander_and_touch(self):
        self.assertTrue(probe.present(FakeI2C({0x20, 0x48})))
        self.assertTrue(probe.present(FakeI2C({0x39, 0x48})))

    def test_missing_touch_or_expander(self):
        self.assertFalse(probe.present(FakeI2C({0x20})))
        self.assertFalse(probe.present(FakeI2C({0x48})))
        self.assertFalse(probe.present(FakeI2C({0x20, 0x38})))  # waveshare 3.5 pair


class AckAll:
    def writeto(self, addr, buf):
        pass


class Exploding:
    def writeto(self, addr, buf):
        raise ValueError("bus error")


class TestProbeRobustness(unittest.TestCase):
    def test_bus_that_acks_every_address_is_not_an_indicator(self):
        self.assertFalse(probe.present(AckAll()))

    def test_unexpected_exception_does_not_escape(self):
        self.assertFalse(probe.present(Exploding()))



class FakeSX1262:
    """SPI mode 0 slave that answers ReadRegister (0x1D addr_hi addr_lo NOP data...) like an SX1262."""

    REGS = {0x0740: 0x14, 0x0741: 0x24}  # LoRa sync word reset value

    def __init__(self, fitted=True):
        self.fitted = fitted
        self.selected = False
        self.reset_pulses = 0
        self._rx = []
        self._tx = []
        self._bit = 0
        self._sck = 0
        self._mosi = 0

    # pin-like lines --------------------------------------------------------
    def nss(self, v=None):
        if v is None:
            return int(not self.selected)
        self.selected = not v
        if self.selected:
            self._rx, self._tx, self._bit = [], [], 0

    def reset(self, v=None):
        if v == 0:
            self.reset_pulses += 1

    def mosi(self, v=None):
        self._mosi = v

    def sck(self, v=None):
        if v == 1 and self._sck == 0 and self.selected:  # rising edge: sample MOSI
            self._rx.append(self._mosi)
            self._bit += 1
            if self._bit % 8 == 0:
                self._byte_done()
        self._sck = v

    def miso(self, v=None):
        if not (self.fitted and self.selected):
            return 0  # pulled down, nothing drives the line
        index = len(self._rx) // 8
        out = self._tx[index] if index < len(self._tx) else 0
        return (out >> (7 - (len(self._rx) % 8))) & 1

    def _byte_done(self):
        bytes_in = [int("".join(map(str, self._rx[i:i + 8])), 2) for i in range(0, len(self._rx), 8)]
        if len(bytes_in) >= 3 and bytes_in[0] == 0x1D:
            addr = (bytes_in[1] << 8) | bytes_in[2]
            # byte 3 returns status, data from byte 4 on, auto-incrementing the address
            self._tx = [0, 0, 0, 0x22] + [self.REGS.get(addr + i, 0) for i in range(8)]


class TestSX1262Probe(unittest.TestCase):
    def probe(self, radio):
        return probe.sx1262_present(radio.nss, radio.reset, radio.sck, radio.mosi, radio.miso,
                                    sleep_ms=lambda ms: None)

    def test_fitted_radio_is_found(self):
        radio = FakeSX1262(fitted=True)
        self.assertTrue(self.probe(radio))
        self.assertEqual(radio.reset_pulses, 1)
        self.assertFalse(radio.selected)  # NSS released afterwards

    def test_missing_radio_is_not_found(self):
        radio = FakeSX1262(fitted=False)
        self.assertFalse(self.probe(radio))
        self.assertFalse(radio.selected)

    def test_stuck_high_miso_is_not_a_radio(self):
        radio = FakeSX1262(fitted=False)
        radio.miso = lambda v=None: 1
        self.assertFalse(self.probe(radio))


if __name__ == "__main__":
    unittest.main()
