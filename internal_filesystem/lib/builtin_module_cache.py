# MicroPython lets a file on sys.path extend a built-in module that is declared extensible
# (time, json, os, ...), so every `import time` first looks for time.py / time.mpy / a time
# package in each sys.path entry: on the internal flash filesystem that is about 20 ms per
# import, paid again on every import inside a function. Built-in modules are not kept in
# sys.modules, so nothing remembers the answer. Caching them there once, after sys.path is
# final, turns each later import into a dictionary lookup; a filesystem extension still wins
# because it is what this first import returns.

import sys

# MP_REGISTER_EXTENSIBLE_MODULE in MicroPython 1.27 (py/, extmod/, ports/esp32)
EXTENSIBLE = ("array", "binascii", "bluetooth", "collections", "cryptolib", "errno", "hashlib",
              "heapq", "io", "json", "machine", "os", "platform", "random", "re", "select",
              "socket", "struct", "time", "websocket")


def cache_builtin_modules(names=EXTENSIBLE):
    for name in names:
        mod = sys.modules.get(name)
        if mod is None:
            try:
                mod = __import__(name)
            except ImportError:
                continue        # not in this build
            sys.modules[name] = mod
        sys.modules.setdefault("u" + name, mod)
