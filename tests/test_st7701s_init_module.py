import sys
import unittest

TYPE17 = "drivers.display.st7701s._st7701s_type17_init"
sys.modules.pop(TYPE17, None)
from drivers.display.st7701s import ST7701S  # noqa: E402


class FakePanel:
    def __init__(self, init_module):
        self._init_module = init_module
        self.display_width = 480
        self.display_height = 480
        self.cmds = []

    def set_params(self, cmd, params=None):
        self.cmds.append(cmd)


class TestInitModule(unittest.TestCase):
    def test_alternative_sequence_is_not_imported_with_the_driver(self):
        self.assertFalse(TYPE17 in sys.modules)

    def test_default_sequence(self):
        panel = FakePanel(None)
        ST7701S._spi_3wire_init(panel)
        self.assertEqual(panel.cmds[0], 0x01)  # SWRESET opens the default sequence

    def test_selected_sequence_is_imported_from_the_package(self):
        panel = FakePanel("_st7701s_type17_init")
        ST7701S._spi_3wire_init(panel)
        self.assertIn(TYPE17, sys.modules)
        self.assertEqual(panel.cmds[0], 0xFF)
        self.assertEqual(panel.cmds[-1], 0x29)


if __name__ == "__main__":
    unittest.main()
