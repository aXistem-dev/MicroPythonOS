# Desktop display size from the MPOS_DISPLAY environment variable ("480x480"), so the same
# build can stand in for boards with other screens. Defaults to 320x240.

DEFAULT = (320, 240)


def display_size(value):
    if not value:
        return DEFAULT
    try:
        w, h = value.lower().split("x")
        w, h = int(w), int(h)
    except Exception:
        return DEFAULT
    if w < 16 or h < 16:
        return DEFAULT
    return (w, h)


def from_environment():
    try:
        import os
        return display_size(os.getenv("MPOS_DISPLAY"))
    except Exception:
        return DEFAULT
