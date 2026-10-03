"""Built-in modules cached in sys.modules at boot: MicroPython looks for a filesystem
extension of an extensible built-in (time, json, ...) on every import of it, which costs a
walk over sys.path each time; once cached, an import is a dictionary lookup."""

import sys
import unittest


class TestBuiltinModuleCache(unittest.TestCase):

    def setUp(self):
        self.saved = dict(sys.modules)

    def tearDown(self):
        for name in list(sys.modules):
            if name not in self.saved:
                del sys.modules[name]

    def test_builtins_land_in_sys_modules(self):
        from builtin_module_cache import cache_builtin_modules
        for name in ("time", "json", "struct"):
            sys.modules.pop(name, None)
        cache_builtin_modules(("time", "json", "struct"))
        import time
        import json
        self.assertIs(sys.modules["time"], time)
        self.assertIs(sys.modules["json"], json)
        self.assertTrue("struct" in sys.modules)

    def test_the_u_prefixed_names_point_at_the_same_module(self):
        from builtin_module_cache import cache_builtin_modules
        cache_builtin_modules(("time",))
        import time
        self.assertIs(sys.modules["utime"], time)

    def test_a_module_this_build_lacks_is_skipped(self):
        from builtin_module_cache import cache_builtin_modules
        cache_builtin_modules(("time", "no_such_builtin_module"))
        self.assertFalse("no_such_builtin_module" in sys.modules)
        self.assertTrue("time" in sys.modules)

    def test_a_module_already_imported_is_kept(self):
        from builtin_module_cache import cache_builtin_modules
        marker = object()
        sys.modules["heapq"] = marker
        try:
            cache_builtin_modules(("heapq",))
            self.assertIs(sys.modules["heapq"], marker)
        finally:
            del sys.modules["heapq"]

    def test_the_default_list_covers_time_and_json(self):
        from builtin_module_cache import EXTENSIBLE
        self.assertTrue("time" in EXTENSIBLE and "json" in EXTENSIBLE)


if __name__ == "__main__":
    unittest.main()
