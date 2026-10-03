"""indicator_rp2040.proto: the InterdeviceMessage codec spoken with the SenseCAP Indicator's
RP2040 (Meshtastic indicator_rp2040 firmware). The golden frames below come from the official
protobuf library and the same interdevice.proto, so equal bytes mean wire compatibility."""

import unittest

from drivers.indicator_rp2040 import proto

# Generated with the official Python protobuf library from interdevice.proto;
# do not edit by hand.
REQUESTS = [
    ('ping', {'id': 7, 'ping': 2}, '58027807'),
    ('beep', {'beep': 100}, '1064'),
    ('tone', {'tone': {'frequency_hz': 880, 'duration_ms': 150}}, '82010608f006109601'),
    ('tone_off', {'tone': {'frequency_hz': 0, 'duration_ms': 0}}, '820100'),
    ('i2c_tx', {'id': 3, 'i2c_transaction': {'address': 68, 'write_data': b'$\x00', 'read_len': 6}}, '1a0808441202240018067803'),
    ('i2c_read_only', {'id': 12, 'i2c_transaction': {'address': 98, 'write_data': b'', 'read_len': 3}}, '1a0408621803780c'),
    ('i2c_scan', {'id': 4, 'i2c_scan': True}, '28017804'),
    ('get', {'id': 300, 'file_transfer': {'operation': 0, 'filepath': '/tiles/12/2100/1360.png', 'offset': 8192, 'length': 4096}}, '3a1f12172f74696c65732f31322f323130302f313336302e706e6730804038802078ac02'),
    ('post', {'id': 5, 'file_transfer': {'operation': 1, 'filepath': '/a.txt', 'filedata': b'hi'}}, '3a0e080112062f612e7478741a0268697805'),
    ('put', {'id': 6, 'file_transfer': {'operation': 2, 'filepath': '/a.txt', 'filedata': b'xxxxxxxxxx', 'offset': 2}}, '3a18080212062f612e7478741a0a7878787878787878787830027806'),
    ('delete', {'id': 8, 'file_transfer': {'operation': 3, 'filepath': '/a.txt'}}, '3a0a080312062f612e7478747808'),
    ('mkdir', {'id': 13, 'file_transfer': {'operation': 4, 'filepath': '/tiles/12'}}, '3a0d080412092f74696c65732f3132780d'),
    ('list', {'id': 9, 'directory_listing': {'directory': '/', 'offset': 16}}, '42050a012f28107809'),
    ('sd_info_req', {'id': 10, 'get_sd_info': True}, '4801780a'),
    ('sd_eject', {'id': 11, 'sd_command': 2}, '7002780b'),
    ('big_id', {'id': 4000000000, 'ping': 2}, '58027880d0acf30e'),
]
RESPONSES = [
    ('pong', {'id': 7, 'pong': 2}, '60027807'),
    ('hello', {'id': 0, 'ping': 2}, '5802'),
    ('nack', {'id': 9, 'nack': True}, '68017809'),
    ('nack_undecodable', {'id': 0, 'nack': True}, '6801'),
    ('i2c_ok', {'id': 3, 'i2c_result': {'status': 1, 'read_data': b'\x01\x02\x03\x04\x05\x06'}}, '220a080112060102030405067803'),
    ('i2c_nack', {'id': 3, 'i2c_result': {'status': 2, 'read_data': b''}}, '220208027803'),
    ('scan_two', {'id': 4, 'i2c_scan_result': b'Db'}, '320244627804'),
    ('scan_none', {'id': 4, 'i2c_scan_result': b''}, '32007804'),
    ('get_ok', {'id': 300, 'file_transfer': {'operation': 0, 'filepath': '/t.png', 'filedata': b'\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\x0c\r\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f !"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~\x7f\x80\x81\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x8b\x8c\x8d\x8e\x8f\x90\x91\x92\x93\x94\x95\x96\x97\x98\x99\x9a\x9b\x9c\x9d\x9e\x9f\xa0\xa1\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xab\xac\xad\xae\xaf\xb0\xb1\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xbb\xbc\xbd\xbe\xbf\xc0\xc1\xc2\xc3\xc4\xc5\xc6\xc7\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\x0c\r\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f !"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~\x7f\x80\x81\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x8b\x8c\x8d\x8e\x8f\x90\x91\x92\x93\x94\x95\x96\x97\x98\x99\x9a\x9b\x9c\x9d\x9e\x9f\xa0\xa1\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xab\xac\xad\xae\xaf\xb0\xb1\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xbb\xbc\xbd\xbe\xbf\xc0\xc1\xc2\xc3\xc4\xc5\xc6\xc7\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\x0c\r\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f !"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~\x7f\x80\x81\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x8b\x8c\x8d\x8e\x8f\x90\x91\x92\x93\x94\x95\x96\x97\x98\x99\x9a\x9b\x9c\x9d\x9e\x9f\xa0\xa1\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xab\xac\xad\xae\xaf\xb0\xb1\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xbb\xbc\xbd\xbe\xbf\xc0\xc1\xc2\xc3\xc4\xc5\xc6\xc7', 'status': 1, 'message': '', 'offset': 4096, 'length': 0, 'file_size': 10000}}, '3aeb0412062f742e706e671ad804000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f404142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f606162636465666768696a6b6c6d6e6f707172737475767778797a7b7c7d7e7f808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9fa0a1a2a3a4a5a6a7a8a9aaabacadaeafb0b1b2b3b4b5b6b7b8b9babbbcbdbebfc0c1c2c3c4c5c6c7000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f404142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f606162636465666768696a6b6c6d6e6f707172737475767778797a7b7c7d7e7f808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9fa0a1a2a3a4a5a6a7a8a9aaabacadaeafb0b1b2b3b4b5b6b7b8b9babbbcbdbebfc0c1c2c3c4c5c6c7000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f404142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f606162636465666768696a6b6c6d6e6f707172737475767778797a7b7c7d7e7f808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9fa0a1a2a3a4a5a6a7a8a9aaabacadaeafb0b1b2b3b4b5b6b7b8b9babbbcbdbebfc0c1c2c3c4c5c6c7200130802040904e78ac02'),
    ('get_nocard', {'id': 301, 'file_transfer': {'operation': 0, 'filepath': '/t.png', 'filedata': b'', 'status': 3, 'message': '', 'offset': 0, 'length': 0, 'file_size': 0}}, '3a0a12062f742e706e67200378ad02'),
    ('put_conflict', {'id': 6, 'file_transfer': {'operation': 2, 'filepath': '/a.txt', 'filedata': b'', 'status': 5, 'message': 'offset', 'offset': 2, 'length': 0, 'file_size': 12}}, '3a18080212062f612e74787420052a066f66667365743002400c7806'),
    ('list_ok', {'id': 9, 'directory_listing': {'directory': '/', 'filenames': ['a.txt', 'tiles/', 'café.txt'], 'status': 1, 'message': '', 'offset': 0, 'total_count': 3}}, '42210a012f1205612e747874120674696c65732f1209636166c3a92e747874180130037809'),
    ('sd_none', {'id': 10, 'sd_info': {'present': False, 'card_type': 0, 'fat_type': 0, 'card_size': 0, 'used_bytes': 0, 'free_bytes': 0, 'stats_valid': False, 'busy': False, 'unformatted': False}}, '5200780a'),
    ('sd_full', {'id': 10, 'sd_info': {'present': True, 'card_type': 3, 'fat_type': 2, 'card_size': 31914983424, 'used_bytes': 1048576, 'free_bytes': 31913934848, 'stats_valid': True, 'busy': False, 'unformatted': False}}, '5218080110031802208080a0f27628808040308080e0f1763801780a'),
    ('sd_busy', {'id': 10, 'sd_info': {'present': False, 'card_type': 0, 'fat_type': 0, 'card_size': 0, 'used_bytes': 0, 'free_bytes': 0, 'stats_valid': False, 'busy': True, 'unformatted': False}}, '52024001780a'),
    ('nmea', {'id': 0, 'nmea': '$GPGGA,123519'}, '0a0d2447504747412c313233353139'),
]


class TestEncode(unittest.TestCase):

    def test_requests_match_the_official_encoding(self):
        for name, form, hexed in REQUESTS:
            self.assertEqual(proto.encode(form).hex(), hexed, name)


class TestDecode(unittest.TestCase):

    def test_responses_decode_with_defaults(self):
        for name, form, hexed in RESPONSES:
            self.assertEqual(proto.decode(bytes.fromhex(hexed)), form, name)

    def test_requests_round_trip(self):
        for name, form, hexed in REQUESTS:
            got = proto.decode(bytes.fromhex(hexed))
            self.assertEqual(proto.encode(got).hex(), hexed, name)

    def test_unknown_fields_are_skipped(self):
        # field 20 (varint), field 21 (fixed32), field 22 (fixed64), field 23 (bytes), then pong=2, id=1
        raw = bytes.fromhex("a00105" + "ad0101020304" + "b1010102030405060708" + "ba0102aabb" + "6002" + "7801")
        self.assertEqual(proto.decode(raw), {"id": 1, "pong": 2})

    def test_truncated_payload_raises_value_error(self):
        with self.assertRaises(ValueError):
            proto.decode(bytes.fromhex("3a0a0801"))


class TestFrame(unittest.TestCase):

    def test_frame_header_is_magic_and_big_endian_length(self):
        payload = bytes(300)
        f = proto.frame(payload)
        self.assertEqual(f[:4], b"\x94\xc3\x01\x2c")
        self.assertEqual(f[4:], payload)


if __name__ == "__main__":
    unittest.main()
