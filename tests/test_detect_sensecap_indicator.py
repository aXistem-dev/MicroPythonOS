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


if __name__ == "__main__":
    unittest.main()
