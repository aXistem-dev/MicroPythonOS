import sys
import unittest

from mpos.testing.mocks import MockMachine, inject_mocks

created = []


class RecordingPin(MockMachine.Pin):
    def __init__(self, pin_number, mode=None, pull=None):
        created.append(pin_number)
        super().__init__(pin_number, mode, pull)


class RecordingMachine(MockMachine):
    Pin = RecordingPin


inject_mocks({"machine": RecordingMachine()})
sys.modules.pop("mpos.usb.usbmanager", None)
from mpos.usb.usbmanager import USBManager  # noqa: E402


class TestBootselPin(unittest.TestCase):
    def setUp(self):
        created.clear()
        self.saved = getattr(USBManager, "bootsel_pin", 0)

    def tearDown(self):
        USBManager.bootsel_pin = self.saved

    def test_board_without_bootsel_pin_never_touches_a_gpio(self):
        # On boards where GPIO0 is wired to something else (e.g. an RGB panel data line),
        # reconfiguring it as a pulled-up input corrupts that signal.
        USBManager.bootsel_pin = None
        self.assertFalse(USBManager._bootsel_held())
        self.assertEqual(created, [])

    def test_default_bootsel_pin_is_gpio0(self):
        self.assertEqual(USBManager.bootsel_pin, 0)
        USBManager._bootsel_held()
        self.assertEqual(created, [0])


if __name__ == "__main__":
    unittest.main()
