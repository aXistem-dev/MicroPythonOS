import sys
import unittest

sys.modules.pop("drivers.display.st7701s._st7701_type17", None)


class Recorder:
    def __init__(self):
        self.cmds = []

    def set_params(self, cmd, params=None):
        self.cmds.append((cmd, bytes(params) if params is not None else None))


class TestType17Sequence(unittest.TestCase):
    def test_sequence_shape(self):
        from drivers.display.st7701s import _st7701_type17
        rec = Recorder()
        _st7701_type17.init(rec)  # real time.sleep_ms delays, < 1 s in total
        cmds = [c for c, _ in rec.cmds]
        self.assertEqual(rec.cmds[0], (0xFF, bytes([0x77, 0x01, 0x00, 0x00, 0x10])))
        self.assertIn(0x3A, cmds)                 # COLMOD
        self.assertIn(0x21, cmds)                 # INVON (the Indicator panel needs inversion)
        self.assertEqual(cmds[-2:], [0x11, 0x29])  # SLPOUT, DISPON last


if __name__ == "__main__":
    unittest.main()
