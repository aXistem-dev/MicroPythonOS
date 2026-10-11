"""LoRa Chat v2 on a board without a LoRa radio (LoRaManager.radioChip is None), or with a radio
on a driver other than PolledSX126x: opening the app says so instead of starting the receive
thread, and leaving it works."""

import sys
import unittest

import lvgl as lv

sys.path.insert(0, "apps/com.micropythonos.lora_chat_v2")
import lora_chat_v2  # noqa: E402
from mpos import LoRaManager  # noqa: E402


class TestLoRaChatV2NoRadio(unittest.TestCase):
    def setUp(self):
        self.saved = (lora_chat_v2.simulation_mode, LoRaManager.radioChip, LoRaManager._holder)
        lora_chat_v2.simulation_mode = False  # as on a device
        LoRaManager.radioChip = None
        LoRaManager._holder = None

    def tearDown(self):
        lora_chat_v2.simulation_mode, LoRaManager.radioChip, LoRaManager._holder = self.saved

    def test_open_and_leave_without_a_radio(self):
        app = lora_chat_v2.LoRaChatV2()
        app.setContentView = lambda content: None
        app.onCreate()
        screen = lv.obj()
        app.onResume(screen)
        self.assertIn("No LoRa radio", app.messages.get_text())
        self.assertIsNone(LoRaManager._holder)
        app.onPause(screen)

    def test_a_radio_without_the_polled_driver_is_left_alone(self):
        LoRaManager.radioChip = object()  # e.g. a board still on the older SX1262 driver
        app = lora_chat_v2.LoRaChatV2()
        app.appFullName = "com.micropythonos.lora_chat_v2"
        app.setContentView = lambda content: None
        app.onCreate()
        screen = lv.obj()
        app.onResume(screen)
        self.assertIn("does not support", app.messages.get_text())
        self.assertIsNone(LoRaManager._holder)
        app.onPause(screen)


if __name__ == "__main__":
    unittest.main()
