import unittest

from mpos.testing.mocks import MockMachine, inject_mocks

inject_mocks({"machine": MockMachine()})


class TestLoraStack(unittest.TestCase):
    def test_upstream_driver_and_wrapper_import(self):
        from lora import SX1262  # noqa: F401
        from mpos.polled_sx126x import PolledSX126x  # noqa: F401
        from mpos.lora_spi_adapter import SPIAdapter, wrap_sx126x_cmd  # noqa: F401

    def test_lock_is_exclusive(self):
        from mpos.lora_manager import LoRaManager
        LoRaManager._holder = None
        LoRaManager.start_watchdog = staticmethod(lambda *a, **k: None)
        LoRaManager.stop_watchdog = staticmethod(lambda *a, **k: None)
        self.assertTrue(LoRaManager.acquire("a"))
        self.assertFalse(LoRaManager.acquire("b"))
        LoRaManager.release("a")
        self.assertTrue(LoRaManager.acquire("b"))
        LoRaManager.release("b")

    def test_legacy_driver_still_imports(self):
        import drivers.lora.sx1262  # noqa: F401


if __name__ == "__main__":
    unittest.main()
