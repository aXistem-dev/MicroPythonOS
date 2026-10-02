import unittest

from mpos.testing.mocks import MockMachine, inject_mocks

inject_mocks({"machine": MockMachine()})
from mpos.lora_manager import LoRaManager  # noqa: E402


class FakeRadio:
    def __init__(self, status=0x20):
        self.cmds = []
        self.status = status
        self._sleep = self._configured = self._rx = None

    def _cmd(self, fmt, *args, n_read=0, **kw):
        self.cmds.append(args[0] if args else None)
        return bytes([self.status] * max(n_read, 1))

    def _clear_irq(self):
        pass

    def _clear_errors(self):
        pass

    def _check_error(self):
        pass


class FakeChip:
    def __init__(self, radio):
        self.radio = radio


class TestBoardResetHook(unittest.TestCase):
    def setUp(self):
        self.saved = (LoRaManager.radioChip, getattr(LoRaManager, "board_reset", None),
                      getattr(LoRaManager, "_tcxo_mv", None))
        self.pulses = []
        LoRaManager.board_reset = lambda: self.pulses.append(1)
        LoRaManager._tcxo_mv = None

    def tearDown(self):
        LoRaManager.radioChip, LoRaManager.board_reset, LoRaManager._tcxo_mv = self.saved

    def test_hook_resets_and_reprograms_irq_mask(self):
        radio = FakeRadio(status=0x20)  # chip mode 2 = STDBY_RC
        LoRaManager.radioChip = FakeChip(radio)
        self.assertTrue(LoRaManager.reset_chip())
        self.assertEqual(self.pulses, [1])
        self.assertIn(0x08, radio.cmds)   # SetDioIrqParams re-sent after the reset

    def test_unresponsive_chip_is_reset_three_times(self):
        LoRaManager.radioChip = FakeChip(FakeRadio(status=0x00))
        self.assertFalse(LoRaManager.reset_chip())
        self.assertEqual(len(self.pulses), 3)


if __name__ == "__main__":
    unittest.main()
