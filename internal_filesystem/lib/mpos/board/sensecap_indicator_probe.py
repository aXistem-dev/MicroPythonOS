# Side-effect-free detection helper for the SenseCAP Indicator (imported by mpos.main).


def _ack(i2c0, addr):
    try:
        i2c0.writeto(addr, b"")
        return True
    except OSError:
        return False


def present(i2c0):
    # PCA9535 expander (0x20, some revisions 0x39) plus FT6336U touch at 0x48 on SDA39/SCL40
    return (_ack(i2c0, 0x20) or _ack(i2c0, 0x39)) and _ack(i2c0, 0x48)
