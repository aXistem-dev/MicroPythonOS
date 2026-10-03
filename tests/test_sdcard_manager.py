import unittest
from mpos import SDCardManager


class TestSDCardManager(unittest.TestCase):

    def setUp(self):
        SDCardManager._instance = None

    def test_unmounted_by_default(self):
        self.assertFalse(SDCardManager.is_mounted())
        self.assertIsNone(SDCardManager.get_mount_point())

    def test_mount_returns_bool(self):
        result = SDCardManager.mount()
        self.assertIsInstance(result, bool)

    def test_mount_format_false_is_default(self):
        result = SDCardManager.mount()
        result_explicit = SDCardManager.mount(format=False)
        self.assertEqual(type(result), type(result_explicit))

    def test_mount_format_true_returns_bool(self):
        result = SDCardManager.mount(format=True)
        self.assertIsInstance(result, bool)

    def test_format_returns_bool(self):
        result = SDCardManager.format()
        self.assertIsInstance(result, bool)
        self.assertFalse(result)

    def test_no_instance_returns_false(self):
        self.assertFalse(SDCardManager.is_mounted())
        self.assertIsNone(SDCardManager.get_mode())
        self.assertIsNone(SDCardManager.get_raw())
        self.assertIsNone(SDCardManager.get_mount_point())


class _FakeCardVFS:
    """A filesystem object for SDCardManager's vfs mode: a card behind another chip."""

    def __init__(self):
        self.card = True
        self.formatted = 0

    def mount(self, readonly, mkfs):
        pass

    def umount(self):
        pass

    def ilistdir(self, path):
        if not self.card:
            raise OSError(19)
        return iter([("maps", 0x4000, 0)])

    def stat(self, path):
        return (0x4000, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    def mkdir(self, path):
        pass

    def rmdir(self, path):
        pass

    def present(self):
        return self.card

    def format(self):
        self.formatted += 1
        return True


class TestSDCardManagerVfsMode(unittest.TestCase):

    def setUp(self):
        SDCardManager._instance = None
        self.card = _FakeCardVFS()
        SDCardManager.init(vfs=self.card)

    def tearDown(self):
        import os
        try:
            os.umount("/sdcard")
        except OSError:
            pass
        SDCardManager._instance = None

    def test_mode_and_mount(self):
        import os
        self.assertEqual(SDCardManager.get_mode(), "vfs")
        self.assertTrue(SDCardManager.mount())
        self.assertEqual(os.listdir("/sdcard"), ["maps"])
        self.assertTrue(SDCardManager.is_mounted())
        self.assertEqual(SDCardManager.get_mount_point(), "/sdcard")

    def test_mounted_but_no_card_is_not_mounted(self):
        SDCardManager.mount()
        self.card.card = False
        self.assertFalse(SDCardManager.is_mounted())
        self.assertIsNone(SDCardManager.get_mount_point())

    def test_format_goes_to_the_card(self):
        self.assertTrue(SDCardManager.format())
        self.assertEqual(self.card.formatted, 1)


if __name__ == "__main__":
    unittest.main()
