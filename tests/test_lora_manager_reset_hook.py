import unittest

from mpos.testing.mocks import MockMachine, inject_mocks

inject_mocks({"machine": MockMachine()})
from mpos.lora_manager import LoRaManager  # noqa: E402


class FakeRadio:
    def __init__(self, status=0x20):
        self.cmds = []
        self.args = []
        self.status = status
        self._sleep = self._configured = self._rx = None

    def _cmd(self, fmt, *args, n_read=0, **kw):
        self.cmds.append(args[0] if args else None)
        self.args.append(args)
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
        self.irq_log = []

    def try_get_status(self):
        return self._watchdog_status

    def disable_irq(self):
        self.irq_log.append("off")

    def enable_irq(self):
        self.irq_log.append("on")

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
        irq = [a for a in radio.args if a and a[0] == 0x08][0]
        self.assertEqual(irq[1], 0x0257)  # incl. PREAMBLE_DETECTED and HEADER_VALID

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

    def test_watchdog_hard_reset_reattaches_dio1(self):
        # The reset detaches the DIO1 interrupt; without re-attaching it no packet reaches the app.
        chip = FakeChip(FakeRadio(status=0x20), watchdog_status=0x00)
        LoRaManager.radioChip = chip
        for _ in range(3):
            LoRaManager._check_once()
        self.assertEqual(chip.irq_log, ["off", "on"])

    def test_reset_keeps_dio2_driving_the_rf_switch(self):
        radio = FakeRadio(status=0x20)
        LoRaManager.radioChip = FakeChip(radio)
        LoRaManager._dio2_rf_sw = True
        self.assertTrue(LoRaManager.reset_chip())
        self.assertIn(0x9D, radio.cmds)   # SetDio2AsRfSwitchCtrl re-sent after the reset


class FakeDio1:
    def __init__(self):
        self.handler = self.trigger = None

    def irq(self, handler=None, trigger=None):
        self.handler, self.trigger = handler, trigger


class FakeDriver:
    def __init__(self, dio1):
        self._dio1 = dio1

    def configure(self, cfg):
        pass

    def set_irq_callback(self, cb):
        pass

    def _radio_isr(self, _):
        pass


class TestPolledIrqReattach(unittest.TestCase):
    def test_enable_irq_restores_the_driver_isr(self):
        from mpos.polled_sx126x import PolledSX126x
        dio1 = FakeDio1()
        driver = FakeDriver(dio1)
        chip = PolledSX126x(driver)
        chip.disable_irq()
        self.assertIsNone(dio1.handler)
        chip.enable_irq()
        self.assertEqual(dio1.handler, driver._radio_isr)
        self.assertEqual(dio1.trigger, MockMachine.Pin.IRQ_RISING)

    def test_enable_irq_without_dio1_is_a_no_op(self):
        from mpos.polled_sx126x import PolledSX126x
        PolledSX126x(FakeDriver(None)).enable_irq()


if __name__ == "__main__":
    unittest.main()
