"""Composable, senior-verified circuit blocks — the ESP32-focused way to build.

A *block* is a small, pre-engineered sub-circuit (an MCU core with its
decoupling and strapping, a USB-C power front-end, a status LED, an I²C bus…).
Each block adds its parts and wires them to shared rails (``3V3`` / ``GND`` /
``5V``) so that *composing blocks* yields a board that already passes the senior
design review — the AI picks blocks instead of placing resistors one by one.

Every block uses auto-generated reference designators, so blocks compose without
ref collisions. Blocks return a dict describing what they expose (e.g. the GPIO
net a peripheral sits on) so callers can wire them together.
"""
from __future__ import annotations

from collections.abc import Callable

from .model import Design

RAIL_3V3 = "3V3"
RAIL_5V = "VBUS"
GND = "GND"


def usb_c_power(d: Design, vout: str = RAIL_3V3) -> dict:
    """USB-C 5V input → AMS1117-3.3 → 3V3, with 5.1k CC sink pulldowns and
    input/output bulk + HF decoupling. The board's power front-end."""
    j = d.add_component("usb_c").ref
    u = d.add_component("regulator_3v3", value="AMS1117-3.3").ref
    cin = d.add_component("capacitor_polarized", value="10uF").ref
    cout = d.add_component("capacitor_polarized", value="22uF").ref
    chf = d.add_component("capacitor", value="100nF").ref
    rcc1 = d.add_component("resistor", value="5.1k").ref
    rcc2 = d.add_component("resistor", value="5.1k").ref
    d.connect(RAIL_5V, f"{j}.vbus", f"{u}.vin", f"{cin}.+")
    d.connect(GND, f"{j}.gnd", f"{u}.gnd", f"{cin}.-", f"{cout}.-",
              f"{chf}.2", f"{rcc1}.2", f"{rcc2}.2")
    d.connect("CC1", f"{j}.cc1", f"{rcc1}.1")
    d.connect("CC2", f"{j}.cc2", f"{rcc2}.1")
    d.connect(vout, f"{u}.vout", f"{cout}.+", f"{chf}.1")
    return {"vout": vout, "refs": [j, u, cin, cout, chf, rcc1, rcc2]}


def esp32_core(d: Design, rail: str = RAIL_3V3) -> dict:
    """ESP32-WROOM with the full support circuit a senior always adds: 10uF
    bulk + 100nF HF decoupling, an EN reset RC (10k + 100nF) with a reset
    button, an IO0 boot pull-up with a boot button. Exposes free GPIOs."""
    u = d.add_component("esp32").ref
    cbulk = d.add_component("capacitor_polarized", value="10uF").ref
    chf = d.add_component("capacitor", value="100nF").ref
    ren = d.add_component("resistor", value="10k").ref
    cen = d.add_component("capacitor", value="100nF").ref
    rio0 = d.add_component("resistor", value="10k").ref
    sw_rst = d.add_component("button").ref
    sw_boot = d.add_component("button").ref
    d.connect(rail, f"{u}.3v3", f"{cbulk}.+", f"{chf}.1", f"{ren}.1", f"{rio0}.1")
    d.connect(GND, f"{u}.gnd", f"{cbulk}.-", f"{chf}.2", f"{cen}.2",
              f"{sw_rst}.2", f"{sw_boot}.2")
    d.connect("EN", f"{u}.en", f"{ren}.2", f"{cen}.1", f"{sw_rst}.1")
    d.connect("IO0", f"{u}.io0", f"{rio0}.2", f"{sw_boot}.1")
    free_gpio = ["io4", "io5", "io16", "io17", "io18", "io19", "io21", "io22",
                 "io23", "io25", "io26", "io27", "io32", "io33"]
    return {"mcu": u, "gpio": [f"{u}.{g}" for g in free_gpio]}


def status_led(d: Design, gpio_pin: str, color: str = "GRN",
               value: str = "330") -> dict:
    """A GPIO-driven status LED with a series current-limiting resistor."""
    r = d.add_component("resistor", value=value).ref
    led = d.add_component("led", value=color).ref
    net = "LED_" + gpio_pin.replace(".", "_").upper()
    d.connect(net, gpio_pin, f"{r}.1")
    d.connect(net + "_A", f"{r}.2", f"{led}.a")
    d.connect(GND, f"{led}.k")
    return {"refs": [r, led]}


def i2c_bus(d: Design, scl_pin: str, sda_pin: str, rail: str = RAIL_3V3) -> dict:
    """I²C bus with 4.7k pull-ups on SCL and SDA and a 4-pin breakout header
    (3V3, GND, SCL, SDA)."""
    rscl = d.add_component("resistor", value="4.7k").ref
    rsda = d.add_component("resistor", value="4.7k").ref
    hdr = d.add_component("header_1x4").ref
    d.connect("SCL", scl_pin, f"{rscl}.1", f"{hdr}.3")
    d.connect("SDA", sda_pin, f"{rsda}.1", f"{hdr}.4")
    d.connect(rail, f"{rscl}.2", f"{rsda}.2", f"{hdr}.1")
    d.connect(GND, f"{hdr}.2")
    return {"refs": [rscl, rsda, hdr]}


def user_button(d: Design, gpio_pin: str, rail: str = RAIL_3V3) -> dict:
    """A push button on a GPIO with a 10k pull-up (active-low input)."""
    r = d.add_component("resistor", value="10k").ref
    sw = d.add_component("button").ref
    d.connect(rail, f"{r}.1")
    d.connect("BTN_" + gpio_pin.replace(".", "_").upper(),
              gpio_pin, f"{r}.2", f"{sw}.1")
    d.connect(GND, f"{sw}.2")
    return {"refs": [r, sw]}


BLOCKS: dict[str, Callable] = {
    "usb_c_power": usb_c_power,
    "esp32_core": esp32_core,
    "status_led": status_led,
    "i2c_bus": i2c_bus,
    "user_button": user_button,
}

BLOCK_HELP = {
    "usb_c_power": "USB-C 5V → 3.3V LDO front-end (CC pulldowns, bulk+HF caps).",
    "esp32_core": "ESP32-WROOM + decoupling + EN reset RC/button + IO0 boot strap/button.",
    "status_led": "GPIO status LED + series resistor. opts: gpio_pin, color, value.",
    "i2c_bus": "I²C pull-ups + 4-pin header. opts: scl_pin, sda_pin.",
    "user_button": "Push button on a GPIO with pull-up. opts: gpio_pin.",
}
