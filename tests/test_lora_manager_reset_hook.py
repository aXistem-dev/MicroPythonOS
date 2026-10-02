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
    def __init__(self, radio, watchdog_status=0x20):
        self.radio = radio
        self._radio = radio
        self._in_op = False
        self._cfg = None
        self._user_callback = None
        self._watchdog_status = watchdog_status

    def try_get_status(self):
        return self._watchdog_status

    def disable_irq(self):
        pass

    def suspend(self):
        pass

    def resume(self):
        pass


class TestBoardResetHook(unittest.TestCase):
    def setUp(self):
        self.saved = (LoRaManager.radioChip, getattr(LoRaManager, "board_reset", None),
                      getattr(LoRaManager, "_tcxo_mv", None), getattr(LoRaManager, "_dio2_rf_sw", False))
        self.pulses = []
        LoRaManager.board_reset = lambda: self.pulses.append(1)
        LoRaManager._tcxo_mv = None

    def tearDown(self):
        (LoRaManager.radioChip, LoRaManager.board_reset, LoRaManager._tcxo_mv,
         LoRaManager._dio2_rf_sw) = self.saved

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


class TestRecoveryOnHookBoards(unittest.TestCase):
    def setUp(self):
        self.saved = (LoRaManager.radioChip, LoRaManager.board_reset,
                      getattr(LoRaManager, "_dio2_rf_sw", False), getattr(LoRaManager, "_tcxo_mv", None))
        self.pulses = []
        LoRaManager.board_reset = lambda: self.pulses.append(1)
        LoRaManager._tcxo_mv = None
        LoRaManager._bad_count = 0
        LoRaManager._last_reinit_ms = 0
        LoRaManager._unresponsive_ms = 0

    def tearDown(self):
        (LoRaManager.radioChip, LoRaManager.board_reset, LoRaManager._dio2_rf_sw,
         LoRaManager._tcxo_mv) = self.saved

    def test_watchdog_hard_reset_reaches_board_hook(self):
        # A wedged chip (status 0x00 three times) must be hardware-reset through the hook.
        LoRaManager.radioChip = FakeChip(FakeRadio(status=0x20), watchdog_status=0x00)
        for _ in range(3):
            LoRaManager._check_once()
        self.assertGreaterEqual(len(self.pulses), 1)

    def test_reset_keeps_dio2_driving_the_rf_switch(self):
        radio = FakeRadio(status=0x20)
        LoRaManager.radioChip = FakeChip(radio)
        LoRaManager._dio2_rf_sw = True
        self.assertTrue(LoRaManager.reset_chip())
        self.assertIn(0x9D, radio.cmds)   # SetDio2AsRfSwitchCtrl re-sent after the reset


if __name__ == "__main__":
    unittest.main()
