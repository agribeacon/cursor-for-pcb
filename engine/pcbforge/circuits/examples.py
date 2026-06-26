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
               notes="USB-C 5V in, AMS1117-3.3 LDO, 10uF in/out caps, power LED.")
    d.add_component("usb_c", "J1")
    d.add_component("regulator_3v3", "U1", "AMS1117-3.3")
    d.add_component("capacitor_polarized", "C1", "10uF")   # input cap
    d.add_component("capacitor_polarized", "C2", "10uF")   # output cap
    d.add_component("capacitor", "C3", "100nF")            # output decoupling
    d.add_component("resistor", "R1", "1k")                # LED limiter
    d.add_component("led", "D1", "GRN")                    # power indicator
    # USB-C 5V input
    d.connect("VBUS", "J1.vbus", "U1.vin", "C1.+")
    d.connect("GND", "J1.gnd", "U1.gnd", "C1.-", "C2.-", "C3.2", "D1.k")
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
    d.add_component("header_1x4", "J2")
    d.connect("VIN", "J1.1", "U1.vin", "C1.+")
    d.connect("GND", "J1.2", "U1.gnd", "C1.-", "C2.-", "C3.2",
              "D1.k", "D2.k", "SW1.2", "J2.4")
    d.connect("3V3", "U1.vout", "C2.+", "C3.1", "R1.1", "R2.1", "SW1.1", "J2.1")
    d.connect("LED1", "R1.2", "D1.a")
    d.connect("LED2", "R2.2", "D2.a")
    return d


EXAMPLES: dict[str, Callable[[], Design]] = {
    "led_resistor": led_resistor,
    "voltage_divider": voltage_divider,
    "power_led_board": power_led_board,
    "usb_3v3": usb_3v3_regulator,
}


def build_example(name: str) -> Design:
    if name not in EXAMPLES:
        raise KeyError(f"Unknown example '{name}'. Have: {list(EXAMPLES)}")
    return EXAMPLES[name]()
