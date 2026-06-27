"""Curated part catalog.

Each entry maps a friendly *type* (what the AI / user names) to the concrete
KiCad symbol (SKiDL ``lib`` + ``part``), a default footprint, and a pin-alias
table so connections can be made by human names (``VI``, ``GND``, ``A``, ``K``)
instead of raw pin numbers.

Start small and real: passives, an LED, a diode, a push button, pin headers,
a linear regulator, and a USB-C power receptacle. Everything here resolves
against the stock KiCad libraries, so generated netlists/boards open cleanly
in KiCad.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PartType:
    key: str                      # friendly type, e.g. "resistor"
    lib: str                      # KiCad symbol library, e.g. "Device"
    part: str                     # KiCad symbol name, e.g. "R"
    footprint: str                # default footprint lib_id
    #: friendly pin name -> KiCad pin *number(s)*. A value may be a single pad
    #: ("2") or a list of pads that are electrically one pin — e.g. a USB-C
    #: VBUS spread across A4/A9/B4/B9 for current capacity.
    pin_aliases: dict[str, "str | list[str]"] = field(default_factory=dict)
    description: str = ""
    default_value: str = ""


# NOTE: pin numbers below match the stock KiCad symbols (verified against
# SharedSupport/symbols/*.kicad_sym). Aliases are case-insensitive at lookup.
CATALOG: dict[str, PartType] = {}


def _reg(pt: PartType, *aliases: str) -> None:
    CATALOG[pt.key] = pt
    for a in aliases:
        CATALOG[a] = pt


_reg(PartType("resistor", "Device", "R", "Resistor_SMD:R_0805_2012Metric",
              {"1": "1", "2": "2", "a": "1", "b": "2"},
              "Resistor", "10k"), "r", "res")

_reg(PartType("capacitor", "Device", "C", "Capacitor_SMD:C_0805_2012Metric",
              {"1": "1", "2": "2", "+": "1", "-": "2"},
              "Unpolarized capacitor", "100nF"), "c", "cap")

_reg(PartType("capacitor_polarized", "Device", "C_Polarized",
              "Capacitor_SMD:CP_Elec_5x5.4",
              {"+": "1", "-": "2", "1": "1", "2": "2"},
              "Polarized capacitor", "10uF"), "cp", "ecap")

_reg(PartType("led", "Device", "LED", "LED_SMD:LED_0805_2012Metric",
              {"a": "2", "anode": "2", "k": "1", "cathode": "1", "1": "1", "2": "2"},
              "Light emitting diode", "RED"), "diode_led")

_reg(PartType("diode", "Device", "D", "Diode_SMD:D_SOD-123",
              {"a": "2", "anode": "2", "k": "1", "cathode": "1", "1": "1", "2": "2"},
              "Diode"), "d")

_reg(PartType("button", "Switch", "SW_Push",
              "Button_Switch_SMD:SW_SPST_PTS645Sx43SMTR92",
              {"1": "1", "2": "2", "a": "1", "b": "2"},
              "Push button", ""), "switch", "sw", "tactile")

_reg(PartType("header_1x2", "Connector_Generic", "Conn_01x02",
              "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
              {"1": "1", "2": "2"}, "2-pin header"), "conn2")

_reg(PartType("header_1x4", "Connector_Generic", "Conn_01x04",
              "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
              {"1": "1", "2": "2", "3": "3", "4": "4"}, "4-pin header"), "conn4")

# AMS1117-3.3 LDO. Stock symbol pin numbers: 1=GND, 2=VO, 3=VI.
_reg(PartType("regulator_3v3", "Regulator_Linear", "AMS1117-3.3",
              "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
              {"gnd": "1", "vo": "2", "vout": "2", "out": "2",
               "vi": "3", "vin": "3", "in": "3"},
              "1A LDO 3.3V", "AMS1117-3.3"), "ldo", "ams1117", "vreg")

_reg(PartType("inductor", "Device", "L", "Inductor_SMD:L_0805_2012Metric",
              {"1": "1", "2": "2"}, "Inductor", "10uH"), "l", "ind")

_reg(PartType("diode_schottky", "Device", "D_Schottky", "Diode_SMD:D_SOD-123",
              {"a": "2", "anode": "2", "k": "1", "cathode": "1", "1": "1", "2": "2"},
              "Schottky diode"), "schottky")

_reg(PartType("zener", "Device", "D_Zener", "Diode_SMD:D_SOD-123",
              {"a": "2", "anode": "2", "k": "1", "cathode": "1", "1": "1", "2": "2"},
              "Zener diode"), "diode_zener")

_reg(PartType("npn", "Transistor_BJT", "BC547", "Package_TO_SOT_SMD:SOT-23",
              {"c": "1", "collector": "1", "b": "2", "base": "2",
               "e": "3", "emitter": "3"}, "NPN transistor"), "transistor", "bjt")

_reg(PartType("nmos", "Transistor_FET", "2N7000", "Package_TO_SOT_SMD:SOT-23",
              {"s": "1", "source": "1", "g": "2", "gate": "2",
               "d": "3", "drain": "3"}, "N-channel MOSFET"), "mosfet")

_reg(PartType("mosfet_logic", "Transistor_FET", "BSS138",
              "Package_TO_SOT_SMD:SOT-23",
              {"g": "1", "gate": "1", "s": "2", "source": "2",
               "d": "3", "drain": "3"}, "Logic-level N-MOSFET"), "bss138")

_reg(PartType("crystal", "Device", "Crystal",
              "Crystal:Crystal_SMD_2012-2Pin_2.0x1.2mm",
              {"1": "1", "2": "2"}, "Crystal", "16MHz"), "xtal")

_reg(PartType("fuse", "Device", "Fuse", "Fuse:Fuse_0805_2012Metric",
              {"1": "1", "2": "2"}, "Fuse"), "f")

_reg(PartType("potentiometer", "Device", "R_Potentiometer",
              "Potentiometer_THT:Potentiometer_Bourns_3296W_Vertical",
              {"1": "1", "2": "2", "3": "3", "w": "2", "wiper": "2"},
              "Potentiometer", "10k"), "pot")

_reg(PartType("ne555", "Timer", "NE555P", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
              {"gnd": "1", "trig": "2", "out": "3", "rst": "4", "reset": "4",
               "cont": "5", "thres": "6", "thresh": "6", "disch": "7", "vcc": "8"},
              "555 timer"), "555", "timer")

_reg(PartType("opamp", "Amplifier_Operational", "LM358",
              "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
              {"out": "1", "in-": "2", "inn": "2", "in+": "3", "inp": "3",
               "vee": "4", "v-": "4", "gnd": "4", "vcc": "8", "v+": "8"},
              "Dual op-amp (channel A)"), "lm358")

# ESP32-WROOM-32 module. GND multi-pad; pin 2 = 3V3, pin 3 = EN, plus all GPIOs.
_ESP32_PINS = {
    "gnd": ["1", "15", "38", "39"], "3v3": "2", "vcc": "2",
    "en": "3", "reset": "3", "boot": "25",
    "io0": "25", "io2": "24", "io4": "26", "io5": "29",
    "io12": "14", "io13": "16", "io14": "13", "io15": "23",
    "io16": "27", "io17": "28", "io18": "30", "io19": "31",
    "io21": "33", "io22": "36", "io23": "37",
    "io25": "10", "io26": "11", "io27": "12",
    "io32": "8", "io33": "9", "io34": "6", "io35": "7",
}
_reg(PartType("esp32", "RF_Module", "ESP32-WROOM-32", "RF_Module:ESP32-WROOM-32",
              _ESP32_PINS, "ESP32-WROOM-32 Wi-Fi/BT module"), "wroom", "esp")

_reg(PartType("reg_5v", "Regulator_Linear", "AMS1117-5.0",
              "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
              {"gnd": "1", "vo": "2", "vout": "2", "out": "2",
               "vi": "3", "vin": "3", "in": "3"},
              "1A LDO 5.0V", "AMS1117-5.0"), "regulator_5v", "ldo5")

_reg(PartType("reg_7805", "Regulator_Linear", "L7805",
              "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
              {"in": "1", "vin": "1", "vi": "1", "gnd": "2",
               "out": "3", "vout": "3", "vo": "3"},
              "7805 5V regulator", "L7805"), "l7805", "7805")

_reg(PartType("screw_2", "Connector", "Screw_Terminal_01x02",
              "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal",
              {"1": "1", "2": "2"}, "2-pin screw terminal"), "terminal", "screw")

_reg(PartType("header_1x6", "Connector_Generic", "Conn_01x06",
              "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical",
              {str(i): str(i) for i in range(1, 7)}, "6-pin header"), "conn6")

_reg(PartType("header_2x4", "Connector_Generic", "Conn_02x04_Odd_Even",
              "Connector_PinHeader_2.54mm:PinHeader_2x04_P2.54mm_Vertical",
              {str(i): str(i) for i in range(1, 9)}, "2x4 header"), "conn2x4")

_reg(PartType("usb_micro", "Connector", "USB_B_Micro",
              "Connector_USB:USB_Micro-B_Amphenol_10103594-0001LF_Horizontal",
              {"vbus": "1", "vcc": "1", "dm": "2", "dp": "3", "id": "4",
               "gnd": "5", "shield": "SH"}, "USB Micro-B receptacle"), "microusb")

# USB-C receptacle (16-pin USB2.0 symbol; GCT footprint has matching pads).
# Power pins are spread across all their physical pads so VBUS/GND carry full
# current and both CC/D+/D- orientations are wired.
_reg(PartType("usb_c", "Connector", "USB_C_Receptacle_USB2.0_16P",
              "Connector_USB:USB_C_Receptacle_GCT_USB4085",
              {"vbus": ["A4", "A9", "B4", "B9"],
               "gnd": ["A1", "A12", "B1", "B12"],
               "cc1": "A5", "cc2": "B5",
               "dp": ["A6", "B6"], "dm": ["A7", "B7"],
               "shield": "SH"},
              "USB 2.0 Type-C receptacle"), "usbc", "type_c")


def resolve(type_key: str) -> PartType:
    pt = CATALOG.get(type_key.strip().lower())
    if pt is None:
        raise KeyError(
            f"Unknown part type '{type_key}'. Known: {sorted(set(p.key for p in CATALOG.values()))}"
        )
    return pt


def pin_numbers(pt: PartType, pin: str) -> list[str]:
    """Resolve a friendly pin name to the list of KiCad pad numbers it maps to.

    Most pins are one pad; power pins (USB-C VBUS/GND) expand to several.
    An unknown name is passed through as a literal single pad number.
    """
    p = str(pin).strip()
    val = pt.pin_aliases.get(p.lower(), p)
    return list(val) if isinstance(val, list) else [val]


def pin_number(pt: PartType, pin: str) -> str:
    """Backward-compatible single-pad resolver (returns the first pad)."""
    return pin_numbers(pt, pin)[0]


def list_types() -> list[dict]:
    seen = {}
    for pt in CATALOG.values():
        if pt.key not in seen:
            pads = set()
            for v in pt.pin_aliases.values():
                pads.update(v if isinstance(v, list) else [v])
            seen[pt.key] = {
                "type": pt.key,
                "symbol": f"{pt.lib}:{pt.part}",
                "footprint": pt.footprint,
                "pins": sorted(pads),
                "pin_names": sorted(pt.pin_aliases.keys()),
                "description": pt.description,
                "default_value": pt.default_value,
            }
    return list(seen.values())
