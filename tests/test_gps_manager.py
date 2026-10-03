"""GPSManager: a board registers where NMEA sentences come from (for example a GPS module on a
co-processor's serial port); apps listen to the sentences and read positions out of them."""

import unittest

from mpos.gps_manager import GPSManager


class FakeSource:
    """Delivers queued sentences through its on_nmea hook when polled."""

    def __init__(self):
        self.on_nmea = None
        self.queue = []
        self.polls = 0

    def poll(self):
        self.polls += 1
        while self.queue:
            self.on_nmea(self.queue.pop(0))


RMC = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
GGA = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"


class TestGPSManager(unittest.TestCase):

    def tearDown(self):
        GPSManager.set_nmea_source(None)
        for cb in list(GPSManager._listeners):
            GPSManager.remove_nmea_listener(cb)

    def test_no_source_until_a_board_registers_one(self):
        self.assertFalse(GPSManager.has_nmea_source())
        self.assertFalse(GPSManager.poll())

    def test_listeners_get_the_sentences_a_poll_brings_in(self):
        src = FakeSource()
        GPSManager.set_nmea_source(src)
        got = []
        GPSManager.add_nmea_listener(got.append)
        src.queue = [RMC, GGA]
        self.assertTrue(GPSManager.poll())
        self.assertEqual(got, [RMC, GGA])
        GPSManager.remove_nmea_listener(got.append)
        src.queue = [RMC]
        GPSManager.poll()
        self.assertEqual(len(got), 2)

    def test_a_failing_listener_does_not_stop_the_others(self):
        src = FakeSource()
        GPSManager.set_nmea_source(src)
        got = []

        def bad(s):
            raise ValueError("boom")

        GPSManager.add_nmea_listener(bad)
        GPSManager.add_nmea_listener(got.append)
        src.queue = [RMC]
        GPSManager.poll()
        self.assertEqual(got, [RMC])

    def test_a_source_that_fails_to_poll_reports_false(self):
        class Broken:
            on_nmea = None

            def poll(self):
                raise OSError(5)

        GPSManager.set_nmea_source(Broken())
        self.assertFalse(GPSManager.poll())

    def test_position_from_rmc_and_gga(self):
        lat, lon = GPSManager.position_from_nmea(RMC)
        self.assertAlmostEqual(lat, 48.1173, places=4)
        self.assertAlmostEqual(lon, 11.516667, places=5)
        lat, lon = GPSManager.position_from_nmea(GGA)
        self.assertAlmostEqual(lat, 48.1173, places=4)

    def test_south_and_west_are_negative(self):
        s = "$GNRMC,001225,A,3355.000,S,15112.000,W,0.0,0.0,281024,,,A"
        lat, lon = GPSManager.position_from_nmea(s)
        self.assertAlmostEqual(lat, -33.916667, places=5)
        self.assertAlmostEqual(lon, -151.2, places=5)

    def test_no_fix_or_a_bad_checksum_gives_none(self):
        void = "$GPRMC,123519,V,,,,,,,230394,,,N"
        no_fix = "$GPGGA,123519,,,,,0,00,,,M,,M,,"
        bad_sum = RMC[:-2] + "00"
        for s in (void, no_fix, bad_sum, "$GPGSV,3,1,11,03,03,111,00*4A", "garbage", ""):
            self.assertIsNone(GPSManager.position_from_nmea(s), s)


if __name__ == "__main__":
    unittest.main()
