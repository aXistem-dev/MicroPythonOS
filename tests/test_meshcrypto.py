import unittest
from binascii import unhexlify as u

import meshcrypto as mc

SEED = u("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
PUB = u("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
SIG = u("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
TPRV = bytes([0x70, 0x65, 0xe1, 0x8f, 0xd9, 0xfa, 0xbb, 0x70, 0xc1, 0xed, 0x90, 0xdc, 0xa1, 0x99, 0x07, 0xde,
              0x69, 0x8c, 0x88, 0xb7, 0x09, 0xea, 0x14, 0x6e, 0xaf, 0xd9, 0x3d, 0x9b, 0x83, 0x0c, 0x7b, 0x60,
              0xc4, 0x68, 0x11, 0x93, 0xc7, 0x9b, 0xbc, 0x39, 0x94, 0x5b, 0xa8, 0x06, 0x41, 0x04, 0xbb, 0x61,
              0x8f, 0x8f, 0xd7, 0xa8, 0x4a, 0x0a, 0xf6, 0xf5, 0x70, 0x33, 0xd6, 0xe8, 0xdd, 0xcd, 0x64, 0x71])
TPUB = u("1ec77175b0918ed206f9ae04ec136d6d5d4315bb26305427f645b492e9350c10")


class TestMeshCrypto(unittest.TestCase):
    def test_rfc8032_vector1(self):
        pub, prv = mc.create_keypair(SEED)
        self.assertEqual(pub, PUB)
        self.assertEqual(mc.sign(b"", pub, prv), SIG)
        self.assertTrue(mc.verify(SIG, b"", PUB))
        self.assertFalse(mc.verify(SIG, b"x", PUB))
        self.assertEqual(mc.derive_pub(prv), pub)

    def test_meshcore_identity_test_keypair_and_shared_secret(self):
        self.assertEqual(mc.derive_pub(TPRV), TPUB)
        pub, prv = mc.create_keypair(SEED)
        s1 = mc.key_exchange(TPUB, prv)
        s2 = mc.key_exchange(pub, TPRV)
        self.assertEqual(s1, s2)
        self.assertNotEqual(s1, bytes(32))

    def test_wrong_lengths_raise(self):
        with self.assertRaises(ValueError):
            mc.create_keypair(SEED[:31])
        with self.assertRaises(ValueError):
            mc.derive_pub(TPRV + b"\x00")
        with self.assertRaises(ValueError):
            mc.key_exchange(TPUB[:31], TPRV)


if __name__ == "__main__":
    unittest.main()
