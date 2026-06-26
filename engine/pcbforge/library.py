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
    #: friendly pin name -> KiCad pin *number* (as string)
    pin_aliases: dict[str, str] = field(default_factory=dict)
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

# USB-C receptacle (power-only 16-pin symbol; GCT footprint has matching pads).
_reg(PartType("usb_c", "Connector", "USB_C_Receptacle_USB2.0_16P",
              "Connector_USB:USB_C_Receptacle_GCT_USB4085",
              {"vbus": "A4", "gnd": "A1", "cc1": "A5", "cc2": "B5",
               "dp": "A6", "dm": "A7", "shield": "SH"},
              "USB 2.0 Type-C receptacle"), "usbc", "type_c")


def resolve(type_key: str) -> PartType:
    pt = CATALOG.get(type_key.strip().lower())
    if pt is None:
        raise KeyError(
            f"Unknown part type '{type_key}'. Known: {sorted(set(p.key for p in CATALOG.values()))}"
        )
    return pt


def pin_number(pt: PartType, pin: str) -> str:
    """Resolve a friendly pin name to a KiCad pin number string."""
    p = str(pin).strip()
    return pt.pin_aliases.get(p.lower(), p)


def list_types() -> list[dict]:
    seen = {}
    for pt in CATALOG.values():
        if pt.key not in seen:
            seen[pt.key] = {
                "type": pt.key,
                "symbol": f"{pt.lib}:{pt.part}",
                "footprint": pt.footprint,
                "pins": sorted(set(pt.pin_aliases.values())),
                "pin_names": sorted(pt.pin_aliases.keys()),
                "description": pt.description,
                "default_value": pt.default_value,
            }
    return list(seen.values())
