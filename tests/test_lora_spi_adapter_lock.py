"""SPIAdapter's lock holds the bus for one radio command (CS low to CS high). Commands come from
more than one thread (an app's radio worker, the DIO1 handler, the watchdog), so the lock must
keep the other threads out, and let the thread that holds it nest."""

import _thread
import time
import unittest

from mpos.testing.mocks import MockMachine, inject_mocks

inject_mocks({"machine": MockMachine()})

from mpos.lora_spi_adapter import SPIAdapter  # noqa: E402


class TestSPIAdapterLock(unittest.TestCase):
    def test_the_holding_thread_can_nest(self):
        spi = SPIAdapter(None)
        self.assertEqual(spi.lock(), 1)
        self.assertEqual(spi.lock(), 2)
        self.assertEqual(spi.unlock(), 1)
        self.assertEqual(spi.unlock(), 0)
        self.assertIsNone(spi._lock_owner)

    def test_another_thread_waits_for_the_command_to_finish(self):
        spi = SPIAdapter(None)
        order = []
        holding = _thread.allocate_lock()
        holding.acquire()
        done = _thread.allocate_lock()
        done.acquire()

        def other():
            spi.lock()
            order.append("other locked")
            holding.release()
            time.sleep_ms(50)
            order.append("other unlocks")
            spi.unlock()
            done.release()

        _thread.start_new_thread(other, ())
        holding.acquire()  # the other thread is in the middle of its command
        spi.lock()
        order.append("main locked")
        spi.unlock()
        done.acquire()
        self.assertEqual(order, ["other locked", "other unlocks", "main locked"])


if __name__ == "__main__":
    unittest.main()
