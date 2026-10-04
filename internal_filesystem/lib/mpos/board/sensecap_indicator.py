import logging

logger = logging.getLogger(__name__)

if __debug__: logger.debug("sensecap_indicator.py initialization")
"""
Hardware initialization for the Seeed SenseCAP Indicator (D1, D1S, D1L and D1Pro)
https://www.seeedstudio.com/SenseCAP-Indicator-D1-p-5643.html (D1L: p-5646, D1Pro: p-5644)
https://wiki.seeedstudio.com/Sensor/SenseCAP/SenseCAP_Indicator/Get_started_with_SenseCAP_Indicator/

https://github.com/Seeed-Solution/SenseCAP_Indicator_ESP32 (components/bsp/src/boards/sensecap_indicator_board.c,
lcd_panel_config.c, components/lora/bsp_sx126x.h)
https://github.com/Seeed-Solution/SenseCAP_Indicator_RP2040
https://github.com/aXistem-dev/indicator_rp2040 (RP2040 firmware for the SD card, Grove I2C and buzzer)

* ESP32-S3R8 (8 MB octal PSRAM), 8 MB flash, CH340 USB-UART on UART0 (the USB-C port)
* 4" 480x480 ST7701S RGB panel; its 3-wire init interface has CS on the IO expander and
  clock/data on GPIO41/48, shared with the LoRa radio's SPI
* FT6336U capacitive touch at 0x48 (reset on the IO expander)
* PCA9535 IO expander at 0x20 (0x39 on some revisions), /INT on GPIO42
* User button on GPIO38 (active low), backlight PWM on GPIO45
* RP2040 co-processor (SD card slot, buzzer, Grove ports) on UART TX19/RX20, reset on expander pin 8.
  With the aXistem-dev/indicator_rp2040 firmware on the RP2040 this file offers its SD card as
  /sdcard, its Grove I2C bus (also the D1S/D1Pro sensors) as a machine.I2C stand-in, and its
  buzzer as an AudioManager output (drivers/indicator_rp2040)
* D1L/D1Pro: SX1262 LoRa radio, SPI on GPIO41/48/47, NSS/RST/BUSY/DIO1 on expander pins 0-3,
  TCXO strap on expander pin 11 (high: 2.4 V TCXO on DIO3, low: crystal)
* D1S/D1Pro: SCD41 CO2, SGP40 tVOC and the Grove AHT20 are wired to the RP2040, not to the ESP32-S3

All four variants share the same ESP32-S3 side. The variants differ only in the radio, which
this file detects (lora_present), and in the RP2040-side sensors.

GPIO0 (BOOT) is the top red bit of the RGB bus, so the USB BOOT-button escape hatch is disabled.
GPIO19/20 (the native USB pins) carry the RP2040 UART, so the sensecap_indicator build target
has no USB device/CDC REPL; the REPL is on the CH340 (UART0).

Known issues:
* A soft reset (Ctrl-D) crashes in the RGB bus teardown (lcd_bus rgb_del); use machine.reset().
* Large host-to-device transfers over the CH340 REPL (mpremote cp, install.sh) can lose data
  past a few KB; small commands are fine. Installing apps over Wi-Fi avoids it.
"""

import sys
import time

import i2c
import lcd_bus
import lvgl as lv
import machine
import rgb_display_framework
from micropython import const

import mpos.ui
from drivers.display.st7701s import ST7701S
from drivers.display.st7701s.pin_spi3wire import PinSpi3Wire
from drivers.io_expander.tca9555 import TCA9555, TCA9555Pin
from mpos import InputManager, SensorManager, USBManager
from mpos.board import sensecap_indicator_probe


# GPIOs
I2C_SDA = const(39)
I2C_SCL = const(40)
EXPANDER_INT = const(42)
USER_BUTTON = const(38)
LCD_BACKLIGHT = const(45)
SPI_SCK = const(41)  # panel 3-wire clock, then radio SPI clock
SPI_MOSI = const(48)  # panel 3-wire data, then radio SPI MOSI
SPI_MISO = const(47)
LCD_DE = const(18)
LCD_VSYNC = const(17)
LCD_HSYNC = const(16)
LCD_PCLK = const(21)
# RGB565 data0..15: blue bits 0-4 on GPIO15..11, green bits 0-5 on GPIO10..5, red bits 0-4 on GPIO4..0
LCD_DATA = (15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0)
RP2040_UART_TX = const(19)
RP2040_UART_RX = const(20)

LCD_WIDTH = const(480)
LCD_HEIGHT = const(480)

# IO expander pins (with the 0x40 marker bit TCA9555 uses for expander pins)
X_LORA_NSS = const(0x40 | 0)
X_LORA_RST = const(0x40 | 1)
X_LORA_BUSY = const(0x40 | 2)
X_LORA_DIO1 = const(0x40 | 3)
X_LCD_CS = const(0x40 | 4)
X_LCD_RST = const(0x40 | 5)
X_TOUCH_INT = const(0x40 | 6)
X_TOUCH_RST = const(0x40 | 7)
X_RP2040_RST = const(0x40 | 8)
X_LORA_TCXO = const(0x40 | 11)

# GPIO0 is a panel data line here: the USB BOOT-button check must leave it alone
USBManager.bootsel_pin = None

# 1) I2C bus + IO expander. The expander keeps its state across an ESP32 reset, so every line
#    this board drives is set explicitly (level first, then direction).
i2c_bus = i2c.I2C.Bus(host=0, scl=I2C_SCL, sda=I2C_SDA, freq=400_000, use_locks=False)
tca = None
for _addr in (0x20, 0x39):
    try:
        tca = TCA9555(i2c_bus, dev_id=_addr)
        break
    except OSError:
        pass
if tca is None:
    raise RuntimeError("sensecap_indicator: no IO expander at 0x20 or 0x39")

lora_nss = TCA9555Pin(tca, X_LORA_NSS, machine.Pin.OUT, value=1)
lora_reset = TCA9555Pin(tca, X_LORA_RST, machine.Pin.OUT, value=1)
lcd_cs = TCA9555Pin(tca, X_LCD_CS, machine.Pin.OUT, value=1)
lcd_reset = TCA9555Pin(tca, X_LCD_RST, machine.Pin.OUT, value=1)
touch_reset = TCA9555Pin(tca, X_TOUCH_RST, machine.Pin.OUT, value=1)
rp2040_reset = TCA9555Pin(tca, X_RP2040_RST, machine.Pin.OUT, value=1)  # low holds the RP2040 in reset
lora_busy = TCA9555Pin(tca, X_LORA_BUSY, machine.Pin.IN)
lora_dio1 = TCA9555Pin(tca, X_LORA_DIO1, machine.Pin.IN)
_touch_int = TCA9555Pin(tca, X_TOUCH_INT, machine.Pin.IN)
_lora_tcxo = TCA9555Pin(tca, X_LORA_TCXO, machine.Pin.IN)

# 2) Panel: hardware reset, then the 3-wire register init on GPIO41/48 (before anything claims the SPI host)
lcd_reset(0)
time.sleep_ms(10)
lcd_reset(1)
time.sleep_ms(120)
spi_3wire = PinSpi3Wire(lcd_cs, machine.Pin(SPI_SCK), machine.Pin(SPI_MOSI))

display_bus = lcd_bus.RGBBus(
    hsync=LCD_HSYNC,
    vsync=LCD_VSYNC,
    de=LCD_DE,
    pclk=LCD_PCLK,
    data0=LCD_DATA[0], data1=LCD_DATA[1], data2=LCD_DATA[2], data3=LCD_DATA[3],
    data4=LCD_DATA[4], data5=LCD_DATA[5], data6=LCD_DATA[6], data7=LCD_DATA[7],
    data8=LCD_DATA[8], data9=LCD_DATA[9], data10=LCD_DATA[10], data11=LCD_DATA[11],
    data12=LCD_DATA[12], data13=LCD_DATA[13], data14=LCD_DATA[14], data15=LCD_DATA[15],
    # Seeed's firmware runs the panel at 18 MHz, but lcd_bus.RGBBus copies LVGL frames into its own
    # PSRAM double buffer and at 18 MHz the scan-out DMA underruns (the image scrolls sideways).
    # 6.5 MHz, as on SQUiXL with the same driver, is stable: about 23 frames/s at 480x480.
    freq=6_500_000,
    hsync_back_porch=50, hsync_front_porch=10, hsync_pulse_width=8,
    vsync_back_porch=20, vsync_front_porch=10, vsync_pulse_width=8,
    hsync_idle_low=False, vsync_idle_low=False, de_idle_high=False,
    pclk_active_low=False,
)
_FB_SIZE = const(LCD_WIDTH * LCD_HEIGHT * 2)
frame_buffer1 = display_bus.allocate_framebuffer(_FB_SIZE, lcd_bus.MEMORY_SPIRAM | lcd_bus.MEMORY_DMA)
frame_buffer2 = display_bus.allocate_framebuffer(_FB_SIZE, lcd_bus.MEMORY_SPIRAM | lcd_bus.MEMORY_DMA)

mpos.ui.main_display = ST7701S(
    data_bus=display_bus,
    spi_3wire=spi_3wire,
    frame_buffer1=frame_buffer1,
    frame_buffer2=frame_buffer2,
    display_width=LCD_WIDTH,
    display_height=LCD_HEIGHT,
    backlight_pin=LCD_BACKLIGHT,
    backlight_on_state=rgb_display_framework.STATE_PWM,
    color_space=lv.COLOR_FORMAT.RGB565,
    color_byte_order=ST7701S.BYTE_ORDER_RGB,
    rgb565_byte_swap=False,
    bus_shared_pins=False,
    init_module="_st7701s_type17_init",
)
mpos.ui.main_display.init()
spi_3wire.deinit()  # hand GPIO41/48 over to the radio; lcd_cs stays high so the panel ignores that traffic
mpos.ui.main_display.set_backlight(100)

# 3) Touch: FT6336U at 0x48, polled. It reports coordinates rotated 180 degrees from the panel.
try:
    import drivers.indev.ft6x36 as ft6x36

    touch_reset(0)
    time.sleep_ms(10)
    touch_reset(1)
    time.sleep_ms(300)
    touch_dev = i2c.I2C.Device(bus=i2c_bus, dev_id=0x48, reg_bits=ft6x36.BITS)
    indev = ft6x36.FT6x36(touch_dev, startup_rotation=lv.DISPLAY_ROTATION._180)
    InputManager.register_indev(indev)
except Exception as e:
    logger.error("sensecap_indicator: touch init failed")
    sys.print_exception(e)

mpos.ui.main_display.set_rotation(lv.DISPLAY_ROTATION._0)

# 4) User button (GPIO38, active low) as a KEYPAD indev: a press goes back
_button = machine.Pin(USER_BUTTON, machine.Pin.IN, machine.Pin.PULL_UP)
_button_last = False


def _button_read_cb(indev, data):
    global _button_last
    data.continue_reading = False
    pressed = _button.value() == 0
    if pressed:
        data.state = lv.INDEV_STATE.PRESSED
        data.key = lv.KEY.ESC
        if not _button_last:  # on the press edge: trigger back-nav (ESC alone doesn't)
            try:
                mpos.ui.back_screen()
            except Exception as e:
                if __debug__: logger.debug("sensecap_indicator: back_screen: %s", e)
    else:
        data.state = lv.INDEV_STATE.RELEASED
    _button_last = pressed


try:
    _keypad = lv.indev_create()
    _keypad.set_type(lv.INDEV_TYPE.KEYPAD)
    _keypad.set_read_cb(_button_read_cb)
    _keypad.set_group(lv.group_get_default())
    _keypad.set_display(lv.display_get_default())
    _keypad.enable(True)
    InputManager.register_indev(_keypad)
except Exception as e:
    logger.error("sensecap_indicator: button init failed: %s", e)

# 5) LoRa radio (D1L/D1Pro only): detect it by reading a register with a known reset value.
#    The radio wiring above (lora_nss, lora_reset, lora_busy, lora_dio1, SPI_*) is left for a LoRa
#    driver to use; DIO1 sits behind the expander, so such a driver polls the IRQ status.
lora_present = False
lora_tcxo_mv = None
try:
    _sck = machine.Pin(SPI_SCK, machine.Pin.OUT, value=0)
    _mosi = machine.Pin(SPI_MOSI, machine.Pin.OUT, value=0)
    _miso = machine.Pin(SPI_MISO, machine.Pin.IN, machine.Pin.PULL_DOWN)
    lora_present = sensecap_indicator_probe.sx1262_present(
        lora_nss, lora_reset, _sck, _mosi, _miso, time.sleep_ms
    )
    for _gpio in (SPI_SCK, SPI_MOSI, SPI_MISO):
        machine.Pin(_gpio, machine.Pin.IN)
    if lora_present:
        lora_tcxo_mv = 2400 if _lora_tcxo() else None
except Exception as e:
    logger.error("sensecap_indicator: LoRa radio probe failed: %s", e)
if __debug__: logger.debug("sensecap_indicator: LoRa radio %s", "present" if lora_present else "absent")


# 6) RP2040 co-processor over UART at 2 Mbaud. With Seeed's original RP2040 firmware it does not
#    answer, and the SD card, Grove I2C and buzzer are left out.
rp2040_link = None
grove_i2c = None
try:
    from drivers.indicator_rp2040.link import Link

    _rp2040_uart = machine.UART(2, baudrate=2_000_000, tx=RP2040_UART_TX, rx=RP2040_UART_RX,
                                rxbuf=16384, timeout=10)
    _link = Link(_rp2040_uart, timeout_ms=500)
    # The RP2040 may still be finishing its own boot: give it a second chance
    if _link.connect(raise_errors=False) or _link.connect(raise_errors=False):
        from drivers.indicator_rp2040.buzzer import RemoteBuzzer
        from drivers.indicator_rp2040.i2c import RemoteI2C
        from drivers.indicator_rp2040.sdfs import SDCard
        from mpos import AudioManager, DeviceManager, SDCardManager

        rp2040_link = _link
        # a tone has no end time: silence one left sounding when the ESP32 reset mid-tune
        rp2040_link.send({"tone": {"frequency_hz": 0}})
        SDCardManager.init(vfs=SDCard(rp2040_link))
        SDCardManager.mount()  # with or without a card: the RP2040 picks up an inserted card
        grove_i2c = RemoteI2C(rp2040_link)
        DeviceManager.registerBus(type="i2c", i2c_bus=grove_i2c)
        AudioManager.add(AudioManager.Output("Buzzer", "buzzer", buzzer_factory=lambda: RemoteBuzzer(rp2040_link)))
        if __debug__: logger.debug("sensecap_indicator: RP2040 link up")
    else:
        logger.warning("sensecap_indicator: no answer from the RP2040 (indicator_rp2040 firmware missing?): "
                       "no SD card, Grove I2C or buzzer")
except Exception as e:
    logger.error("sensecap_indicator: RP2040 link setup failed: %s", e)

# 7) No IMU on this board: MCU temperature only
SensorManager.init(None)

if __debug__: logger.debug("sensecap_indicator.py finished")
