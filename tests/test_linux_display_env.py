import unittest

from mpos.board.display_env import display_size


class TestDisplayEnv(unittest.TestCase):
    def test_default_when_unset(self):
        self.assertEqual(display_size(None), (320, 240))

    def test_parses_width_by_height(self):
        self.assertEqual(display_size("480x480"), (480, 480))
        self.assertEqual(display_size("800X480"), (800, 480))

    def test_bad_value_falls_back(self):
        self.assertEqual(display_size("big"), (320, 240))
        self.assertEqual(display_size("0x10"), (320, 240))
