"""PolledSX126x's DIO1 handler is scheduled work: it can run in the middle of another radio
command on the same thread, or during send()/recv(). It must not touch the radio then."""

import unittest

from mpos import polled_sx126x
from mpos.lora_spi_adapter import SPIAdapter
from mpos.polled_sx126x import PolledSX126x


class FakeRadio:
    def __init__(self):
        self._dio1 = object()
        self._spi = SPIAdapter(None)
        self.irq_reads = 0

    def _get_irq(self):
        self.irq_reads += 1
        return 1 << 1

    def configure(self, cfg):
        pass

    def set_irq_callback(self, cb):
        self.isr = cb


class FakeMicropython:
    def __init__(self, full=False):
        self.scheduled = []
        self.full = full

    def schedule(self, fn, arg):
        if self.full:
            raise RuntimeError("schedule queue full")
        self.scheduled.append((fn, arg))


class TestDio1Handler(unittest.TestCase):
    def setUp(self):
        self.radio = FakeRadio()
        self.chip = PolledSX126x(self.radio)
        self.events = []
        self.chip._user_callback = self.events.append
        self.mp = FakeMicropython()
        self._saved = polled_sx126x.micropython
        polled_sx126x.micropython = self.mp

    def tearDown(self):
        polled_sx126x.micropython = self._saved

    def test_idle_radio_delivers_the_flags(self):
        self.radio.isr()
        self.assertEqual(self.events, [2])

    def test_mid_command_on_this_thread_defers(self):
        self.radio._spi.lock()
        self.radio.isr()
        self.assertEqual(self.radio.irq_reads, 0)
        self.assertEqual(len(self.mp.scheduled), 1)
        self.radio._spi.unlock()
        fn, arg = self.mp.scheduled.pop()
        fn(arg)
        self.assertEqual(self.events, [2])

    def test_a_full_schedule_queue_drops_the_edge_without_touching_the_radio(self):
        self.mp.full = True
        self.radio._spi.lock()
        self.radio.isr()
        self.radio._spi.unlock()
        self.assertEqual(self.radio.irq_reads, 0)
        self.assertEqual(self.events, [])

    def test_send_and_recv_handle_their_own_flags(self):
        self.chip._in_op = True
        self.radio.isr()
        self.assertEqual(self.radio.irq_reads, 0)
        self.assertEqual(self.mp.scheduled, [])

    def test_a_command_on_another_thread_does_not_defer(self):
        self.radio._spi._lock_count = 1
        self.radio._spi._lock_owner = -1
        self.radio.isr()
        self.assertEqual(self.events, [2])


if __name__ == "__main__":
    unittest.main()
