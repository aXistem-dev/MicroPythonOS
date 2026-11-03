import sys
import unittest

TYPE17 = "drivers.display.st7701s._st7701s_init_type17"
sys.modules.pop(TYPE17, None)
import drivers.display.st7701s as st7701s_package  # noqa: E402
from drivers.display.st7701s import ST7701S  # noqa: E402


class FakePanel:
    def __init__(self):
        self.display_width = 480
        self.display_height = 480
        self.cmds = []

    def set_params(self, cmd, params=None):
        self.cmds.append(cmd)


class TestInitType(unittest.TestCase):
    def test_alternative_sequence_is_not_imported_with_the_driver(self):
        self.assertFalse(TYPE17 in sys.modules)

    def test_default_sequence(self):
        panel = FakePanel()
        ST7701S._spi_3wire_init(panel)
        self.assertEqual(panel.cmds[0], 0x01)  # SWRESET opens the default sequence

    def test_init_type_runs_the_sequence_from_the_package_and_drops_it(self):
        panel = FakePanel()
        ST7701S._spi_3wire_init(panel, 17)
        self.assertEqual(panel.cmds[0], 0xFF)
        self.assertEqual(panel.cmds[-1], 0x29)
        self.assertFalse(TYPE17 in sys.modules)
        self.assertFalse(hasattr(st7701s_package, "_st7701s_init_type17"))

    def test_unknown_type(self):
        with self.assertRaises(ImportError):
            ST7701S._spi_3wire_init(FakePanel(), 99)


if __name__ == "__main__":
    unittest.main()
