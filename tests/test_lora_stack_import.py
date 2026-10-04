import unittest

from mpos.testing.mocks import MockMachine, inject_mocks

inject_mocks({"machine": MockMachine()})


class TestLoraStack(unittest.TestCase):
    def test_driver_and_wrapper_import(self):
        from lora import SX1262  # noqa: F401
        from mpos.polled_sx126x import PolledSX126x  # noqa: F401
        from mpos.lora_spi_adapter import SPIAdapter, wrap_sx126x_cmd  # noqa: F401

    def test_legacy_driver_still_imports(self):
        import drivers.lora.sx1262  # noqa: F401

    def test_radio_lock_is_exclusive(self):
        from mpos.lora_manager import LoRaManager
        saved = (LoRaManager.__dict__["start_watchdog"], LoRaManager.__dict__["stop_watchdog"], LoRaManager._holder)
        LoRaManager.start_watchdog = staticmethod(lambda *a, **k: None)
        LoRaManager.stop_watchdog = staticmethod(lambda *a, **k: None)
        LoRaManager._holder = None
        try:
            self.assertTrue(LoRaManager.acquire("a"))
            self.assertFalse(LoRaManager.acquire("b"))
            LoRaManager.release("a")
            self.assertTrue(LoRaManager.acquire("b"))
            LoRaManager.release("b")
        finally:
            LoRaManager.start_watchdog, LoRaManager.stop_watchdog, LoRaManager._holder = saved


if __name__ == "__main__":
    unittest.main()
