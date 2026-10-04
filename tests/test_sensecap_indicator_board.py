"""Boot sequence of mpos/board/sensecap_indicator.py against fake hardware (no LVGL display needed)."""

import sys
import unittest

import mpos
import mpos.ui
from mpos.testing.mocks import create_mock_module


class Anything:
    """Permissive stand-in: every attribute is another (cached) Anything, calls return one too."""

    def __init__(self, name="lv"):
        self._name = name

    def __getattr__(self, attr):
        if attr.startswith("__"):
            raise AttributeError(attr)
        value = Anything(self._name + "." + attr)
        setattr(self, attr, value)
        return value

    def __call__(self, *args, **kwargs):
        return Anything(self._name + "()")


class FakePin:
    IN = 1
    OUT = 3
    PULL_UP = 1
    PULL_DOWN = 2

    gpios = {}

    def __init__(self, number, mode=None, pull=None, value=None):
        self.number = number
        self.mode = None
        self.pull = None
        self.level = 1 if number == 38 else 0  # user button idles high (pull-up)
        FakePin.gpios[number] = self
        self.init(mode, pull, value=value)

    def init(self, mode=None, pull=None, value=None):
        if mode is not None:
            self.mode = mode
            self.pull = pull
        if value is not None:
            self.level = value

    def value(self, v=None):
        if v is None:
            return self.level
        self.level = v

    __call__ = value

    def irq(self, handler=None, trigger=None):
        self.irq_handler, self.irq_trigger = handler, trigger


class FakePWM:
    def __init__(self, pin, freq=0, duty_u16=0):
        self.pin, self.freq, self.duty = pin, freq, duty_u16

    def duty_u16(self, value=None):
        if value is None:
            return self.duty
        self.duty = value


class FakeSPIBus:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeSPIDevice:
    MSB = 0

    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeSX1262:
    last = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeSX1262.last = self


class FakePolled:
    def __init__(self, radio):
        self.radio = radio


class FakeSPIAdapter:
    def __init__(self, device):
        self.device = device


class FakeLoRaManager:
    radioChip = None
    board_reset = None
    _dio2_rf_sw = False
    _tcxo_mv = None
    _tcxo_start_us = None


class FakeUART:
    last = None

    def __init__(self, uart_id, **kwargs):
        self.uart_id = uart_id
        self.kwargs = kwargs
        FakeUART.last = self


class FakeLink:
    answers = []
    last = None

    def __init__(self, uart, timeout_ms=None):
        self.uart = uart
        self.timeout_ms = timeout_ms
        self.connects = 0
        self.sent = []
        FakeLink.last = self

    def send(self, msg):
        self.sent.append(msg)

    def connect(self, raise_errors=True):
        self.connects += 1
        return FakeLink.answers.pop(0) if FakeLink.answers else False


class FakeRemote:
    def __init__(self, link):
        self.link = link


class FakeAudioManager:
    outputs = []

    class Output:
        def __init__(self, name, kind, buzzer_factory=None, **kwargs):
            self.name, self.kind, self.buzzer_factory = name, kind, buzzer_factory

    @classmethod
    def add(cls, output):
        cls.outputs.append(output)


class FakeDeviceManager:
    buses = []

    @classmethod
    def registerBus(cls, type="i2c", i2c_bus=None):
        cls.buses.append((type, i2c_bus))


class FakeSDCardManager:
    vfs = None
    mounted = 0

    @classmethod
    def init(cls, vfs=None, **kwargs):
        cls.vfs = vfs

    @classmethod
    def mount(cls, format=False):
        cls.mounted += 1


class FakeExpander:
    """i2c.I2C.Device stand-in holding a PCA9535 register file (power-on: OUT 0xFFFF, CFG 0xFFFF)."""

    present = {0x20}
    instances = []

    def __init__(self, bus=None, dev_id=None, **kw):
        self.dev_id = dev_id
        self.regs = bytearray([0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0xFF, 0xFF])
        self._ptr = 0
        FakeExpander.instances.append(self)

    def write(self, data):
        if self.dev_id not in FakeExpander.present:
            raise OSError(19)
        self._ptr = data[0]
        if len(data) > 1:
            self.regs[self._ptr:self._ptr + len(data) - 1] = data[1:]

    def read(self, n):
        return bytes(self.regs[self._ptr:self._ptr + n])

    def driven(self, pin):
        """Level the expander drives on an output pin, or None if the pin is an input."""
        word = self.regs[6] | (self.regs[7] << 8)
        if word & (1 << pin):
            return None
        return 1 if (self.regs[2] | (self.regs[3] << 8)) & (1 << pin) else 0

    def set_input(self, pin, level):
        byte, bit = divmod(pin, 8)
        if level:
            self.regs[byte] |= 1 << bit
        else:
            self.regs[byte] &= ~(1 << bit)


class FakeRGBBus:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def allocate_framebuffer(self, size, caps):
        return bytearray(0)


class FakeST7701S:
    BYTE_ORDER_RGB = 0
    last = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.backlight = None
        self.rotation = None
        FakeST7701S.last = self

    def init(self):
        spi = self.kwargs["spi_3wire"]
        spi.init(8, 8)
        spi.tx_param(0x29)

    def set_backlight(self, value):
        self.backlight = value

    def set_rotation(self, rotation):
        self.rotation = rotation


class FakeFT6x36:
    BITS = 8

    def __init__(self, device, startup_rotation=None):
        self.device = device
        self.startup_rotation = startup_rotation


class FakeInputManager:
    indevs = []

    @classmethod
    def register_indev(cls, indev):
        cls.indevs.append(indev)


class FakeSensorManager:
    init_args = None

    @classmethod
    def init(cls, i2c_bus, **kwargs):
        cls.init_args = (i2c_bus,)


class FakeUSBManager:
    bootsel_pin = 0


class FakeTaskManager:
    supervised = []

    @classmethod
    def create_supervised_task(cls, factory, restart_delay_ms=200, restart_on_return=False):
        cls.supervised.append(factory)

    @staticmethod
    async def sleep_ms(ms):
        pass


BOARD = "mpos.board.sensecap_indicator"
FRESH = (BOARD, "drivers.io_expander.tca9555", "drivers.display.st7701s.pin_spi3wire")
X_LORA_NSS, X_LORA_RST, X_LCD_CS, X_LCD_RST, X_TOUCH_RST, X_RP2040_RST, X_LORA_TCXO = 0, 1, 4, 5, 7, 8, 11


class BoardBoot(unittest.TestCase):
    def setUp(self):
        FakePin.gpios = {}
        FakeExpander.instances = []
        FakeExpander.present = {0x20}
        FakeInputManager.indevs = []
        FakeSensorManager.init_args = None
        FakeUSBManager.bootsel_pin = 0
        FakeTaskManager.supervised = []
        FakeLoRaManager.radioChip = None
        FakeLoRaManager.board_reset = None
        FakeLoRaManager._dio2_rf_sw = False
        FakeLoRaManager._tcxo_mv = None
        FakeSX1262.last = None
        FakeLink.answers = [True]
        FakeLink.last = None
        FakeAudioManager.outputs = []
        FakeDeviceManager.buses = []
        FakeSDCardManager.vfs = None
        FakeSDCardManager.mounted = 0
        self.radio_error = None
        self.probe_calls = []
        self.probe_result = True
        self.probe_error = None
        self.tcxo_level = 0
        self._saved_modules = {}
        self._saved_attrs = []

    def tearDown(self):
        for name, module in self._saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for obj, attr, value in reversed(self._saved_attrs):
            setattr(obj, attr, value)

    def _module(self, name, module):
        if name not in self._saved_modules:
            self._saved_modules[name] = sys.modules.get(name)
        sys.modules[name] = module

    def _attr(self, obj, attr, value):
        self._saved_attrs.append((obj, attr, getattr(obj, attr, None)))
        setattr(obj, attr, value)

    def _fake_probe(self, nss, reset, sck, mosi, miso, sleep_ms):
        expander = self.expander()
        self.probe_calls.append({
            "lcd_cs": expander.driven(X_LCD_CS),
            "nss": expander.driven(X_LORA_NSS),
            "sck": (sck.number, sck.mode),
            "mosi": (mosi.number, mosi.mode),
            "miso": (miso.number, miso.mode, miso.pull),
        })
        expander.set_input(X_LORA_TCXO, self.tcxo_level)
        if self.probe_error:
            raise self.probe_error
        return self.probe_result

    def expander(self):
        return [e for e in FakeExpander.instances if e.dev_id in FakeExpander.present][-1]

    def boot(self):
        spi = create_mock_module("SPI", Bus=FakeSPIBus, Device=FakeSPIDevice)
        machine = create_mock_module("machine", Pin=FakePin, PWM=FakePWM, SPI=spi, UART=FakeUART)
        import drivers.indicator_rp2040
        for sub, attrs in (("link", {"Link": FakeLink}), ("buzzer", {"RemoteBuzzer": FakeRemote}),
                           ("i2c", {"RemoteI2C": FakeRemote}), ("sdfs", {"SDCard": FakeRemote})):
            module = create_mock_module("drivers.indicator_rp2040." + sub, **attrs)
            self._module("drivers.indicator_rp2040." + sub, module)
            self._attr(drivers.indicator_rp2040, sub, module)

        def make_radio(**kwargs):
            if self.radio_error:
                raise self.radio_error
            return FakeSX1262(**kwargs)

        self._module("lora", create_mock_module("lora", SX1262=make_radio))
        self._module("mpos.lora_spi_adapter", create_mock_module(
            "mpos.lora_spi_adapter", SPIAdapter=FakeSPIAdapter, wrap_sx126x_cmd=lambda radio: None))
        self._module("mpos.polled_sx126x", create_mock_module("mpos.polled_sx126x", PolledSX126x=FakePolled))
        i2c = create_mock_module("i2c", I2C=create_mock_module("I2C", Bus=lambda **kw: "i2c-bus", Device=FakeExpander))
        lcd_bus = create_mock_module("lcd_bus", RGBBus=FakeRGBBus, MEMORY_SPIRAM=1, MEMORY_DMA=2)
        ft6x36 = create_mock_module("drivers.indev.ft6x36", FT6x36=FakeFT6x36, BITS=8)
        for name in FRESH + ("drivers.io_expander.expander_irq",):
            self._module(name, None)
            sys.modules.pop(name, None)
        self._module("machine", machine)
        self._module("i2c", i2c)
        self._module("lcd_bus", lcd_bus)
        self._module("lvgl", Anything())
        self._module("drivers.indev.ft6x36", ft6x36)
        import drivers.indev
        self._attr(drivers.indev, "ft6x36", ft6x36)
        import drivers.display.st7701s
        self._attr(drivers.display.st7701s, "ST7701S", FakeST7701S)
        self._attr(mpos, "InputManager", FakeInputManager)
        self._attr(mpos, "SensorManager", FakeSensorManager)
        self._attr(mpos, "USBManager", FakeUSBManager)
        self._attr(mpos, "TaskManager", FakeTaskManager)
        self._attr(mpos, "LoRaManager", FakeLoRaManager)
        self._attr(mpos, "AudioManager", FakeAudioManager)
        self._attr(mpos, "DeviceManager", FakeDeviceManager)
        self._attr(mpos, "SDCardManager", FakeSDCardManager)
        self._attr(mpos.ui, "main_display", None)
        self._attr(mpos.ui, "back_screen", lambda: self.back_calls.append(1))
        self.back_calls = []
        from mpos.board import sensecap_indicator_probe
        self._attr(sensecap_indicator_probe, "sx1262_present", self._fake_probe)
        __import__(BOARD)
        return sys.modules[BOARD]


class TestBoot(BoardBoot):
    def test_panel_configuration(self):
        board = self.boot()
        panel = FakeST7701S.last
        self.assertIs(mpos.ui.main_display, panel)
        self.assertEqual(panel.kwargs["init_module"], "_st7701s_type17_init")
        self.assertEqual(panel.kwargs["backlight_pin"], 45)
        self.assertEqual((panel.kwargs["display_width"], panel.kwargs["display_height"]), (480, 480))
        self.assertEqual(panel.backlight, 100)
        self.assertEqual(board.display_bus.kwargs["freq"], 6_500_000)
        self.assertEqual(board.display_bus.kwargs["data15"], 0)  # GPIO0: top red bit

    def test_boot_button_check_stays_off_gpio0(self):
        self.boot()
        self.assertIsNone(FakeUSBManager.bootsel_pin)

    def test_expander_outputs_are_driven_high(self):
        self.boot()
        expander = self.expander()
        for pin in (X_LORA_NSS, X_LORA_RST, X_LCD_CS, X_LCD_RST, X_TOUCH_RST, X_RP2040_RST):
            self.assertEqual(expander.driven(pin), 1, "expander pin %d" % pin)
        self.assertIsNone(expander.driven(X_LORA_TCXO))

    def test_expander_fallback_address(self):
        FakeExpander.present = {0x39}
        self.boot()
        self.assertEqual(self.expander().dev_id, 0x39)

    def test_no_expander_is_an_error(self):
        FakeExpander.present = set()
        with self.assertRaises(RuntimeError):
            self.boot()

    def test_touch_and_button_are_registered(self):
        self.boot()
        touch = [i for i in FakeInputManager.indevs if isinstance(i, FakeFT6x36)]
        self.assertEqual(len(touch), 1)
        self.assertEqual(len(FakeInputManager.indevs), 2)

    def test_button_press_goes_back_once(self):
        board = self.boot()
        data = Anything("data")
        FakePin.gpios[38].level = 0
        board._button_read_cb(None, data)
        board._button_read_cb(None, data)
        self.assertEqual(len(self.back_calls), 1)
        FakePin.gpios[38].level = 1
        board._button_read_cb(None, data)
        FakePin.gpios[38].level = 0
        board._button_read_cb(None, data)
        self.assertEqual(len(self.back_calls), 2)

    def test_mcu_temperature_only(self):
        self.boot()
        self.assertEqual(FakeSensorManager.init_args, (None,))


class TestLoRaDetection(BoardBoot):
    def test_radio_probe_runs_with_the_panel_deselected(self):
        self.boot()
        self.assertEqual(len(self.probe_calls), 1)
        call = self.probe_calls[0]
        self.assertEqual(call["lcd_cs"], 1)
        self.assertEqual(call["nss"], 1)
        self.assertEqual(call["sck"], (41, FakePin.OUT))
        self.assertEqual(call["mosi"], (48, FakePin.OUT))
        self.assertEqual(call["miso"], (47, FakePin.IN, FakePin.PULL_DOWN))

    def test_spi_gpios_are_released_after_the_probe(self):
        self.boot()
        for gpio in (41, 47, 48):
            self.assertEqual(FakePin.gpios[gpio].mode, FakePin.IN, "GPIO%d" % gpio)
            self.assertIsNone(FakePin.gpios[gpio].pull, "GPIO%d" % gpio)

    def test_d1l_with_crystal(self):
        board = self.boot()
        self.assertTrue(board.lora_present)
        self.assertIsNone(board.lora_tcxo_mv)

    def test_d1l_with_tcxo(self):
        self.tcxo_level = 1
        board = self.boot()
        self.assertTrue(board.lora_present)
        self.assertEqual(board.lora_tcxo_mv, 2400)

    def test_d1_without_radio(self):
        self.probe_result = False
        self.tcxo_level = 1
        board = self.boot()
        self.assertFalse(board.lora_present)
        self.assertIsNone(board.lora_tcxo_mv)

    def test_probe_failure_does_not_stop_the_boot(self):
        self.probe_error = OSError(5)
        board = self.boot()
        self.assertFalse(board.lora_present)
        self.assertEqual(FakeSensorManager.init_args, (None,))


class TestRP2040(BoardBoot):
    def test_link_runs_on_uart2_at_2_mbaud(self):
        self.boot()
        uart = FakeUART.last
        self.assertEqual(uart.uart_id, 2)
        self.assertEqual((uart.kwargs["tx"], uart.kwargs["rx"], uart.kwargs["baudrate"]), (19, 20, 2_000_000))
        self.assertTrue(FakeLink.last.uart is uart)

    def test_sd_grove_and_buzzer_are_offered(self):
        board = self.boot()
        self.assertTrue(board.rp2040_link is FakeLink.last)
        self.assertTrue(isinstance(FakeSDCardManager.vfs, FakeRemote))
        self.assertEqual(FakeSDCardManager.mounted, 1)
        self.assertEqual(FakeDeviceManager.buses, [("i2c", board.grove_i2c)])
        self.assertEqual([(o.name, o.kind) for o in FakeAudioManager.outputs], [("Buzzer", "buzzer")])
        buzzer = FakeAudioManager.outputs[0].buzzer_factory()
        self.assertTrue(buzzer.link is board.rp2040_link)

    def test_a_tone_left_sounding_before_the_reset_is_silenced(self):
        self.boot()
        self.assertEqual(FakeLink.last.sent, [{"tone": {"frequency_hz": 0}}])

    def test_second_try_when_the_rp2040_is_still_booting(self):
        FakeLink.answers = [False, True]
        board = self.boot()
        self.assertEqual(FakeLink.last.connects, 2)
        self.assertTrue(board.rp2040_link is FakeLink.last)

    def test_original_rp2040_firmware_leaves_the_peripherals_out(self):
        FakeLink.answers = [False, False]
        board = self.boot()
        self.assertIsNone(board.rp2040_link)
        self.assertIsNone(board.grove_i2c)
        self.assertIsNone(FakeSDCardManager.vfs)
        self.assertEqual(FakeAudioManager.outputs, [])
        self.assertEqual(FakeSensorManager.init_args, (None,))


if __name__ == "__main__":
    unittest.main()
