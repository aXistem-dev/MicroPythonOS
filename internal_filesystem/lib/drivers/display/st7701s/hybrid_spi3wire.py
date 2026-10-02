# 3-wire (9-bit) SPI for ST7701S register init with chip-select on an IO expander and clock/data
# on native GPIO (e.g. lines shared with another SPI device that is created afterwards).
# Implements the rgb_display_framework spi_3wire contract.

import machine


class HybridSpi3Wire:
    def __init__(self, cs, clk, mosi):
        self._cs = cs
        self._clk = clk
        self._mosi = mosi
        self._cmd_bits = 8
        self._param_bits = 8

    def init(self, cmd_bits, param_bits):
        self._cmd_bits = cmd_bits
        self._param_bits = param_bits
        self._clk.init(machine.Pin.OUT, value=0)
        self._mosi.init(machine.Pin.OUT, value=0)
        self._cs(1)

    def _word(self, dc, value, nbits):
        clk, mosi = self._clk, self._mosi
        clk(0)
        mosi(dc)
        clk(1)
        for i in range(nbits - 1, -1, -1):
            clk(0)
            mosi((value >> i) & 1)
            clk(1)

    def tx_param(self, cmd, params=None):
        self._cs(0)
        self._word(0, cmd, self._cmd_bits)
        if params:
            for b in params:
                self._word(1, b, self._param_bits)
        self._clk(0)
        self._cs(1)

    def deinit(self):
        self._clk.init(machine.Pin.IN)
        self._mosi.init(machine.Pin.IN)
