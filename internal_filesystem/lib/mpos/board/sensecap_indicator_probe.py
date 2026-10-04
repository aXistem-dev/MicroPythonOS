# Side-effect-free detection helpers for the Seeed SenseCAP Indicator (imported by mpos.main and the board file).


def _ack(i2c0, addr):
    try:
        i2c0.writeto(addr, b"")
        return True
    except Exception:
        return False


def present(i2c0):
    # PCA9535 expander (0x20, some revisions 0x39) plus FT6336U touch at 0x48 on SDA39/SCL40.
    # 0x77 must stay silent: a floating bus that acknowledges every address is not this board.
    if _ack(i2c0, 0x77):
        return False
    return (_ack(i2c0, 0x20) or _ack(i2c0, 0x39)) and _ack(i2c0, 0x48)


def _xfer(sck, mosi, miso, byte):
    # SPI mode 0, MSB first: the slave drives MISO before the rising edge, on which both sides sample
    value = 0
    for i in range(7, -1, -1):
        mosi((byte >> i) & 1)
        value = (value << 1) | (1 if miso() else 0)
        sck(1)
        sck(0)
    return value


def sx1262_present(nss, reset, sck, mosi, miso, sleep_ms):
    # The D1L and D1Pro carry an SX1262, the D1 and D1S do not. Reset the radio and read the LoRa
    # sync word registers (0x0740/0x0741), whose reset value 0x14 0x24 identifies a live SX126x.
    # All lines are pin-like callables; MISO must be pulled down so an empty footprint reads 0x00.
    nss(1)
    sck(0)
    reset(0)
    sleep_ms(2)
    reset(1)
    sleep_ms(20)  # cold start to STDBY_RC takes a few ms; BUSY is not used (it floats when unfitted)
    nss(0)
    try:
        for b in (0x1D, 0x07, 0x40, 0x00):  # ReadRegister, address, NOP (returns status)
            _xfer(sck, mosi, miso, b)
        sync = (_xfer(sck, mosi, miso, 0x00), _xfer(sck, mosi, miso, 0x00))
    finally:
        nss(1)
    return sync == (0x14, 0x24)
