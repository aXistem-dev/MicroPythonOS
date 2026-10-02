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


if __name__ == "__main__":
    unittest.main()
