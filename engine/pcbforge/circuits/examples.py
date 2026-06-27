"""Reference circuits — the "easy boards first" set.

Each builder returns a fully-connected :class:`Design`. They double as smoke
tests and as few-shot examples for the AI.
"""
from __future__ import annotations

from collections.abc import Callable

from ..model import Design


def led_resistor() -> Design:
    """The hello-world: a 5V rail driving an LED through a current limiter."""
    d = Design(name="led_blinker",
               notes="5V -> 330R -> LED -> GND. Classic indicator.")
    d.add_component("resistor", "R1", "330")
    d.add_component("led", "D1", "RED")
    d.connect("VCC", "R1.1")
    d.connect("LED_A", "R1.2", "D1.a")
    d.connect("GND", "D1.k")
    return d


def voltage_divider() -> Design:
    d = Design(name="voltage_divider",
               notes="Two 10k resistors halve VIN to VOUT.")
    d.add_component("resistor", "R1", "10k")
    d.add_component("resistor", "R2", "10k")
    d.connect("VIN", "R1.1")
    d.connect("VOUT", "R1.2", "R2.1")
    d.connect("GND", "R2.2")
    return d


def usb_3v3_regulator() -> Design:
    """USB-C 5V -> AMS1117-3.3 LDO -> 3V3, with decoupling and a power LED.

    This mirrors the 'Solar Soil Node Power' board shape from the UI mock-up:
    a USB-C power input feeding a 3.3V regulator for an MCU rail.
    """
    d = Design(name="usb_c_3v3",
               notes="USB-C 5V in, AMS1117-3.3 LDO, in/out bulk + HF decoupling, "
                     "5.1k CC pulldowns (sink), power LED.")
    d.add_component("usb_c", "J1")
    d.add_component("regulator_3v3", "U1", "AMS1117-3.3")
    d.add_component("capacitor_polarized", "C1", "10uF")   # input bulk cap
    d.add_component("capacitor_polarized", "C2", "22uF")   # output bulk cap
    d.add_component("capacitor", "C3", "100nF")            # output HF decoupling
    d.add_component("resistor", "R1", "1k")                # LED limiter
    d.add_component("led", "D1", "GRN")                    # power indicator
    d.add_component("resistor", "R2", "5.1k")              # CC1 pulldown (sink)
    d.add_component("resistor", "R3", "5.1k")              # CC2 pulldown (sink)
    # USB-C 5V input
    d.connect("VBUS", "J1.vbus", "U1.vin", "C1.+")
    d.connect("GND", "J1.gnd", "U1.gnd", "C1.-", "C2.-", "C3.2", "D1.k",
              "R2.2", "R3.2")
    # USB-C sink advertisement: 5.1k from each CC to GND
    d.connect("CC1", "J1.cc1", "R2.1")
    d.connect("CC2", "J1.cc2", "R3.1")
    # 3.3V output rail
    d.connect("3V3", "U1.vout", "C2.+", "C3.1", "R1.1")
    d.connect("LED_A", "R1.2", "D1.a")
    return d


def power_led_board() -> Design:
    """A realistic, fully-autoroutable board: 2-pin 5V input -> AMS1117-3.3 ->
    3V3 rail with bulk + HF decoupling, two indicator LEDs, a button, and a
    4-pin breakout header. No fine-pitch parts, so the autorouter clears DRC."""
    d = Design(name="power_led_board",
               notes="5V header -> 3.3V LDO, 2 LEDs, button, 3V3 breakout.")
    d.add_component("header_1x2", "J1")
    d.add_component("regulator_3v3", "U1", "AMS1117-3.3")
    d.add_component("capacitor_polarized", "C1", "10uF")
    d.add_component("capacitor_polarized", "C2", "22uF")
    d.add_component("capacitor", "C3", "100nF")
    d.add_component("resistor", "R1", "1k")
    d.add_component("led", "D1", "GRN")
    d.add_component("resistor", "R2", "1k")
    d.add_component("led", "D2", "RED")
    d.add_component("button", "SW1")
    d.add_component("header_1x2", "J2")            # 3V3 breakout (no floating pins)
    d.connect("VIN", "J1.1", "U1.vin", "C1.+")
    d.connect("GND", "J1.2", "U1.gnd", "C1.-", "C2.-", "C3.2",
              "D1.k", "D2.k", "SW1.2", "J2.2")
    d.connect("3V3", "U1.vout", "C2.+", "C3.1", "R1.1", "R2.1", "SW1.1", "J2.1")
    d.connect("LED1", "R1.2", "D1.a")
    d.connect("LED2", "R2.2", "D2.a")
    return d


def esp32_dev_board() -> Design:
    """A complete ESP32-WROOM dev board done to a senior standard:

    USB-C power (5.1k CC sink pulldowns) → AMS1117-3.3 with in/out bulk caps →
    ESP32 with proper decoupling (10uF bulk + 100nF HF), an EN reset RC (10k +
    100nF) and reset button, an IO0 boot pull-up + boot button, and a status LED.
    Every IC power pin is decoupled and no strap pin floats."""
    d = Design(name="esp32_dev_board",
               notes="ESP32-WROOM dev board: USB-C, 3.3V LDO, full decoupling, "
                     "EN reset RC + button, IO0 boot strap + button, status LED.")
    d.add_component("usb_c", "J1")
    d.add_component("regulator_3v3", "U2", "AMS1117-3.3")
    d.add_component("esp32", "U1")
    d.add_component("capacitor_polarized", "C1", "10uF")   # LDO input bulk
    d.add_component("capacitor_polarized", "C2", "22uF")   # LDO output bulk
    d.add_component("capacitor", "C3", "100nF")            # 3V3 HF decoupling
    d.add_component("capacitor_polarized", "C4", "10uF")   # ESP32 bulk
    d.add_component("capacitor", "C5", "100nF")            # EN reset RC cap
    d.add_component("resistor", "R1", "10k")               # EN pull-up
    d.add_component("resistor", "R2", "10k")               # IO0 boot pull-up
    d.add_component("resistor", "R3", "5.1k")              # CC1 pulldown
    d.add_component("resistor", "R4", "5.1k")              # CC2 pulldown
    d.add_component("resistor", "R5", "1k")                # LED limiter
    d.add_component("led", "D1", "GRN")                    # status LED
    d.add_component("button", "SW1")                       # EN reset
    d.add_component("button", "SW2")                       # IO0 boot

    d.connect("VBUS", "J1.vbus", "U2.vin", "C1.+")
    d.connect("GND", "J1.gnd", "U2.gnd", "U1.gnd", "C1.-", "C2.-", "C3.2",
              "C4.-", "C5.2", "D1.k", "R3.2", "R4.2", "SW1.2", "SW2.2")
    d.connect("3V3", "U2.vout", "U1.3v3", "C2.+", "C3.1", "C4.+",
              "R1.1", "R2.1", "R5.1")
    d.connect("EN", "U1.en", "R1.2", "C5.1", "SW1.1")       # reset RC + button
    d.connect("IO0", "U1.io0", "R2.2", "SW2.1")             # boot strap + button
    d.connect("CC1", "J1.cc1", "R3.1")
    d.connect("CC2", "J1.cc2", "R4.1")
    d.connect("LED_A", "R5.2", "D1.a")
    return d


def esp32_iot_node() -> Design:
    """An ESP32 IoT node assembled purely from senior-verified blocks: USB-C
    power, ESP32 core, an I²C sensor header, two status LEDs and a user button.
    Composing blocks guarantees the board passes the senior review."""
    from .. import blocks as B
    d = Design(name="esp32_iot_node",
               notes="Block-composed: USB-C power + ESP32 core + I2C + 2 LEDs + button.")
    B.usb_c_power(d)
    core = B.esp32_core(d)
    g = core["gpio"]
    B.i2c_bus(d, scl_pin=g[0], sda_pin=g[1])     # io4 / io5
    B.status_led(d, g[2], "GRN")                 # io16
    B.status_led(d, g[3], "RED")                 # io17
    B.user_button(d, g[4])                       # io18
    return d


EXAMPLES: dict[str, Callable[[], Design]] = {
    "led_resistor": led_resistor,
    "voltage_divider": voltage_divider,
    "power_led_board": power_led_board,
    "usb_3v3": usb_3v3_regulator,
    "esp32_dev_board": esp32_dev_board,
    "esp32_iot_node": esp32_iot_node,
}


def build_example(name: str) -> Design:
    if name not in EXAMPLES:
        raise KeyError(f"Unknown example '{name}'. Have: {list(EXAMPLES)}")
    return EXAMPLES[name]()
