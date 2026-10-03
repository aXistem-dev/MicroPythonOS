"""PolledSX126x.send() returns as soon as the transmission is done, so the caller can switch
the radio back to receive before an immediate answer starts. A repeater forwards a direct
packet (a trace, for instance) with no delay: its preamble starts a few milliseconds after
ours ends and lasts tens of milliseconds, so every millisecond the radio stays off receive
loses replies."""

import time
import unittest

from mpos.polled_sx126x import PolledSX126x

_TX_DONE = 1 << 0


class FakeRadio:
    """Just enough of lora.SX1262 for send(): TX_DONE rises `airtime_ms` after start_send()."""

    def __init__(self, airtime_ms):
        self.airtime_ms = airtime_ms
        self.t_start = None
        self._dio1 = None

    def _get_irq(self):
        if self.t_start is not None and time.ticks_diff(time.ticks_ms(), self.t_start) >= self.airtime_ms:
            return _TX_DONE
        return 0

    def _clear_errors(self):
        pass

    def prepare_send(self, data):
        pass

    def start_send(self):
        self.t_start = time.ticks_ms()

    def poll_send(self):
        return True

    def get_time_on_air_us(self, n):
        return self.airtime_ms * 1000

    def configure(self, cfg):
        pass

    def set_irq_callback(self, cb):
        pass


class TestTxTurnaround(unittest.TestCase):

    def _send(self, airtime_ms):
        radio = FakeRadio(airtime_ms)
        chip = PolledSX126x(radio)
        t0 = time.ticks_ms()
        n, err = chip.send(b"\x26\x00" + bytes(10))
        done_at = time.ticks_diff(time.ticks_ms(), t0)
        return n, err, done_at

    def test_returns_right_after_tx_done(self):
        n, err, ms = self._send(60)
        self.assertEqual(err, 0)
        self.assertTrue(60 <= ms <= 75, "send() took %d ms for a 60 ms packet" % ms)

    def test_a_late_tx_done_is_still_seen(self):
        radio = FakeRadio(60)
        radio.get_time_on_air_us = lambda n: 30 * 1000      # the estimate is short
        chip = PolledSX126x(radio)
        t0 = time.ticks_ms()
        n, err = chip.send(b"\x26\x00" + bytes(10))
        ms = time.ticks_diff(time.ticks_ms(), t0)
        self.assertEqual(err, 0)
        self.assertTrue(60 <= ms <= 75, "send() took %d ms" % ms)

    def test_tx_that_never_finishes_times_out(self):
        radio = FakeRadio(10 ** 6)
        radio.get_time_on_air_us = lambda n: 30 * 1000      # a normal estimate, no TX_DONE ever
        chip = PolledSX126x(radio)
        n, err = chip.send(b"\x26\x00" + bytes(10))
        self.assertTrue(err != 0)


if __name__ == "__main__":
    unittest.main()
