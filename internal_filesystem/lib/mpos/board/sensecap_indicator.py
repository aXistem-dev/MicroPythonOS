import logging

logger = logging.getLogger(__name__)

"""
Seeed SenseCAP Indicator (D1, D1S, D1L, D1Pro).

* ESP32-S3R8 (8 MB octal PSRAM), 8 MB flash, CH340 USB-UART on UART0
* 4" 480x480 ST7701S RGB panel; 3-wire init: CS on the IO expander, clock/data on GPIO41/48
* FT6336U touch at 0x48 (reset on the expander, polled)
* PCA9535 IO expander at 0x20 (fallback 0x39), /INT on GPIO42
* SX1262 LoRa (D1L/D1Pro): SPI GPIO41/48/47, NSS/RST/BUSY/DIO1 on expander P0.0-P0.3,
  TCXO strap on expander pin 11 (high: TCXO on DIO3 at 2.4 V; low: crystal)
* RP2040 co-processor (SD card, buzzer, Grove I2C, sensors on D1S/D1Pro) on UART TX19/RX20,
  reset on expander pin 8; spoken to with interdevice.proto (drivers/indicator_rp2040)

Sources: Seeed-Solution/SenseCAP_Indicator_ESP32 (bsp/src/boards/sensecap_indicator_board.c,
lcd_panel_config.c, lora/bsp_sx126x.h) and the ESPHome "SEEED-INDICATOR-D1" panel model.
"""

import sys
import time

import i2c
import lcd_bus
import lvgl as lv
import machine
from micropython import const

import mpos.ui
from drivers.display.st7701s import ST7701S
from drivers.display.st7701s.hybrid_spi3wire import HybridSpi3Wire
from drivers.io_expander.expander_irq import ExpanderIRQ
from drivers.io_expander.tca9555 import TCA9555, ExpanderPin
from mpos import InputManager, SensorManager, TaskManager, USBManager

I2C_SDA = const(39)
I2C_SCL = const(40)
EXP_INT = const(42)
USER_BTN = const(38)
LCD_BL = const(45)
SPI_SCK = const(41)
SPI_MOSI = const(48)
SPI_MISO = const(47)
LCD_DE = const(18)
LCD_VSYNC = const(17)
LCD_HSYNC = const(16)
LCD_PCLK = const(21)
LCD_W = const(480)
LCD_H = const(480)
# data0..15 in LVGL RGB565 bit order: blue bits 0-4, green bits 0-5, red bits 0-4
RGB_DATA = (15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0)

# expander pin numbers (0-15)
X_NSS, X_RST, X_BUSY, X_DIO1 = 0, 1, 2, 3
X_LCD_CS, X_LCD_RST, X_TP_INT, X_TP_RST = 4, 5, 6, 7
X_RP2040_RST, X_TCXO = 8, 11

RP2040_UART = (2, 19, 20)

# GPIO0 is the red MSB of the RGB bus here: the USB BOOT-button check must not reconfigure it
USBManager.bootsel_pin = None

# 1) I2C + expander (state survives an ESP32 reset: set every line explicitly)
i2c_bus = i2c.I2C.Bus(host=0, scl=I2C_SCL, sda=I2C_SDA, freq=400_000, use_locks=False)
for _addr in (0x20, 0x39):
    try:
        tca = TCA9555(i2c_bus, dev_id=_addr)
        tca.read_inputs()
        break
    except OSError:
        tca = None
if tca is None:
    raise RuntimeError("sensecap_indicator: no PCA9535 at 0x20/0x39")

radio_nss = ExpanderPin(tca, X_NSS, machine.Pin.OUT, value=1)
radio_rst = ExpanderPin(tca, X_RST, machine.Pin.OUT, value=1)
lcd_cs = ExpanderPin(tca, X_LCD_CS, machine.Pin.OUT, value=1)
lcd_rst = ExpanderPin(tca, X_LCD_RST, machine.Pin.OUT, value=1)
tp_rst = ExpanderPin(tca, X_TP_RST, machine.Pin.OUT, value=1)
rp2040_reset = ExpanderPin(tca, X_RP2040_RST, machine.Pin.OUT, value=1)
radio_busy = ExpanderPin(tca, X_BUSY, machine.Pin.IN)
radio_dio1 = ExpanderPin(tca, X_DIO1, machine.Pin.IN)
_tp_int = ExpanderPin(tca, X_TP_INT, machine.Pin.IN)
_tcxo = ExpanderPin(tca, X_TCXO, machine.Pin.IN)

# 2) panel reset + 3-wire register init on GPIO41/48 (before anything claims SPI host 1)
lcd_rst(0)
time.sleep_ms(10)
lcd_rst(1)
time.sleep_ms(120)
spi_3wire = HybridSpi3Wire(lcd_cs, machine.Pin(SPI_SCK), machine.Pin(SPI_MOSI))

display_bus = lcd_bus.RGBBus(
    hsync=LCD_HSYNC, vsync=LCD_VSYNC, de=LCD_DE, pclk=LCD_PCLK,
    data0=RGB_DATA[0], data1=RGB_DATA[1], data2=RGB_DATA[2], data3=RGB_DATA[3],
    data4=RGB_DATA[4], data5=RGB_DATA[5], data6=RGB_DATA[6], data7=RGB_DATA[7],
    data8=RGB_DATA[8], data9=RGB_DATA[9], data10=RGB_DATA[10], data11=RGB_DATA[11],
    data12=RGB_DATA[12], data13=RGB_DATA[13], data14=RGB_DATA[14], data15=RGB_DATA[15],
    # Seeed's firmware runs 18 MHz, but lcd_bus.RGBBus copies LVGL frames into its own PSRAM
    # double buffer; at 18 MHz the scan-out DMA underruns and the image scrolls. 6.5 MHz (as on
    # SQUiXL with the same driver) is stable: about 23 frames/s at 480x480.
    freq=6_500_000,
    hsync_back_porch=50, hsync_front_porch=10, hsync_pulse_width=8,
    vsync_back_porch=20, vsync_front_porch=10, vsync_pulse_width=8,
    hsync_idle_low=False, vsync_idle_low=False, de_idle_high=False,
    pclk_active_low=False,
)
_FB = const(LCD_W * LCD_H * 2)
fb1 = display_bus.allocate_framebuffer(_FB, lcd_bus.MEMORY_SPIRAM | lcd_bus.MEMORY_DMA)
fb2 = display_bus.allocate_framebuffer(_FB, lcd_bus.MEMORY_SPIRAM | lcd_bus.MEMORY_DMA)

mpos.ui.main_display = ST7701S(
    data_bus=display_bus,
    spi_3wire=spi_3wire,
    frame_buffer1=fb1,
    frame_buffer2=fb2,
    display_width=LCD_W,
    display_height=LCD_H,
    color_space=lv.COLOR_FORMAT.RGB565,
    color_byte_order=ST7701S.BYTE_ORDER_RGB,
    rgb565_byte_swap=False,
    bus_shared_pins=False,
    init_module='_st7701_type17',
)
mpos.ui.main_display.init()
spi_3wire.deinit()   # free GPIO41/48 for the radio's SPI host
lcd_cs(1)            # keep the panel deaf to radio SPI traffic

backlight = machine.PWM(machine.Pin(LCD_BL), freq=20_000, duty_u16=65535)


def set_backlight(percent):
    percent = max(0, min(100, percent))
    backlight.duty_u16(int(percent * 65535 // 100))


mpos.ui.main_display.set_backlight = set_backlight  # the panel driver has no backlight pin of its own
mpos.ui.main_display.set_backlight(100)

# 3) touch: FT6336U at 0x48, polled
try:
    tp_rst(0)
    time.sleep_ms(10)
    tp_rst(1)
    time.sleep_ms(300)
    import drivers.indev.ft6x36 as ft6x36
    _touch_dev = i2c.I2C.Device(bus=i2c_bus, dev_id=0x48, reg_bits=ft6x36.BITS)
    # The FT6336U reports coordinates rotated 180 degrees relative to the panel (measured)
    indev = ft6x36.FT6x36(_touch_dev, startup_rotation=lv.DISPLAY_ROTATION._180)
    InputManager.register_indev(indev)
except Exception as e:
    logger.error("sensecap_indicator: touch init failed")
    sys.print_exception(e)

mpos.ui.main_display.set_rotation(lv.DISPLAY_ROTATION._0)

# 4) user button (GPIO38, active low) as a KEYPAD indev: press = back
_btn = machine.Pin(USER_BTN, machine.Pin.IN, machine.Pin.PULL_UP)
_btn_last = False


def _btn_read_cb(indev, data):
    global _btn_last
    data.continue_reading = False
    pressed = _btn.value() == 0
    if pressed:
        data.state = lv.INDEV_STATE.PRESSED
        data.key = lv.KEY.ESC
        if not _btn_last:
            try:
                mpos.ui.back_screen()
            except Exception as e:
                if __debug__: logger.debug("sensecap_indicator: back_screen: %s", e)
    else:
        data.state = lv.INDEV_STATE.RELEASED
    _btn_last = pressed


try:
    _kp = lv.indev_create()
    _kp.set_type(lv.INDEV_TYPE.KEYPAD)
    _kp.set_read_cb(_btn_read_cb)
    _kp.set_group(lv.group_get_default())
    _kp.set_display(lv.display_get_default())
    _kp.enable(True)
    InputManager.register_indev(_kp)
except Exception as e:
    logger.error("sensecap_indicator: button init failed: %s", e)

# 5) shared expander interrupt + radio wiring for the LoRa layer (radio itself is set up there)
expander_irq = ExpanderIRQ(tca, machine.Pin(EXP_INT, machine.Pin.IN, machine.Pin.PULL_UP))


async def _expander_irq_safety_net():
    while True:
        expander_irq.check()
        await TaskManager.sleep_ms(100)


TaskManager.create_supervised_task(_expander_irq_safety_net, restart_on_return=True)
# 6) LoRa radio (D1L/D1Pro): SX1262 on SPI host 1, control lines on the expander, polled
#    (DIO1 sits behind the expander, so the driver reads IRQ status over SPI).
_tcxo_high = sum(_tcxo() for _ in range(5))
radio_tcxo_mv = 2400 if _tcxo_high >= 3 else None


def _radio_reset_pulse():
    radio_rst(0)
    time.sleep_ms(2)
    radio_rst(1)
    time.sleep_ms(10)


radio_spi_bus = None
radio_spi = None
try:
    from lora import SX1262
    from mpos import LoRaManager
    from mpos.lora_spi_adapter import SPIAdapter, wrap_sx126x_cmd
    from mpos.polled_sx126x import PolledSX126x

    radio_spi_bus = machine.SPI.Bus(host=1, mosi=SPI_MOSI, miso=SPI_MISO, sck=SPI_SCK)
    radio_spi = machine.SPI.Device(spi_bus=radio_spi_bus, freq=8_000_000, cs=-1, polarity=0,
                                   phase=0, firstbit=machine.SPI.Device.MSB, bits=8)
    _radio = SX1262(spi=SPIAdapter(radio_spi), cs=radio_nss, busy=radio_busy, dio1=None,
                    dio2_rf_sw=True, dio3_tcxo_millivolts=radio_tcxo_mv,
                    dio3_tcxo_start_time_us=1000, reset=radio_rst)
    wrap_sx126x_cmd(_radio)
    LoRaManager.radioChip = PolledSX126x(_radio)
    LoRaManager.board_reset = _radio_reset_pulse
    LoRaManager._dio2_rf_sw = True
    LoRaManager._tcxo_mv = radio_tcxo_mv
    LoRaManager._tcxo_start_us = 1000
except Exception as e:  # D1/D1S have no SX1262: BUSY never drops, construction fails
    logger.warning("sensecap_indicator: no LoRa radio (%s)", e)
lcd_cs(1)  # the panel must never see radio SPI traffic

# 6) SOC temperature for the top bar (no IMU on this board)
try:
    SensorManager.init(None)
except Exception as e:
    logger.error("sensecap_indicator: sensor init failed: %s", e)

# 7) RP2040 co-processor: SD card, Grove I2C port and buzzer, over UART2 at 2 Mbaud. Needs the
#    indicator_rp2040 peripheral-bridge firmware (with buzzer tones) on the RP2040; with
#    Seeed's stock firmware it does not answer and none of the three is offered.
rp2040_link = None
grove_i2c = None
try:
    from drivers.indicator_rp2040.link import Link
    _rp_uart = machine.UART(RP2040_UART[0], baudrate=2_000_000, tx=RP2040_UART[1], rx=RP2040_UART[2],
                            rxbuf=16384, timeout=0)
    _link = Link(_rp_uart, timeout_ms=500)
    _ok = False
    for _attempt in range(2):        # the RP2040 may be finishing its own boot
        if _link.connect(raise_errors=False):
            _ok = True
            break
    if _ok:
        from drivers.indicator_rp2040.buzzer import RemoteBuzzer
        from drivers.indicator_rp2040.i2c import RemoteI2C
        from drivers.indicator_rp2040.sdfs import SDCard
        from mpos import AudioManager, DeviceManager, SDCardManager
        rp2040_link = _link
        # a tone has no end time: silence one left sounding when the ESP32 reset mid-tune
        rp2040_link.send({"tone": {"frequency_hz": 0}})
        SDCardManager.init(vfs=SDCard(rp2040_link))
        SDCardManager.mount()        # mounted with or without a card: the RP2040 notices insertion
        grove_i2c = RemoteI2C(rp2040_link)
        DeviceManager.registerBus(type="i2c", i2c_bus=grove_i2c)
        AudioManager.add(AudioManager.Output("Buzzer", "buzzer",
                                             buzzer_factory=lambda: RemoteBuzzer(rp2040_link)))
        if __debug__: logger.debug("sensecap_indicator: RP2040 link up")
    else:
        logger.warning("sensecap_indicator: the RP2040 does not answer (no bridge firmware?): "
                       "no SD card, Grove I2C or buzzer")
except Exception as e:
    logger.error("sensecap_indicator: RP2040 link setup failed: %s", e)

if __debug__: logger.debug("sensecap_indicator.py finished")
