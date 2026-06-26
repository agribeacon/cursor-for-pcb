"""A small, dependency-free chat -> engine intent parser.

This is the brain behind the web UI's chat box when no LLM is wired in. It
understands a compact command grammar plus some natural phrasing so a user can
type "load usb", "add a 330 ohm resistor", "connect gnd u1.gnd c1.-", "build".

The *full* AI experience (free-form design from a sentence) comes from driving
the MCP server with Claude Code — this parser keeps the standalone web demo
useful and fully offline/testable.
"""
from __future__ import annotations

import re

from pcbforge import Design, library
from pcbforge.circuits import EXAMPLES, build_example

_EXAMPLE_ALIASES = {
    "usb": "usb_3v3", "usb-c": "usb_3v3", "usbc": "usb_3v3", "3v3": "usb_3v3",
    "power": "power_led_board", "board": "power_led_board",
    "regulator": "power_led_board", "leds": "power_led_board",
    "led": "led_resistor", "blinker": "led_resistor", "blink": "led_resistor",
    "divider": "voltage_divider", "voltage": "voltage_divider",
}

_TYPE_WORDS = {
    "resistor": "resistor", "res": "resistor", "r": "resistor",
    "capacitor": "capacitor", "cap": "capacitor", "c": "capacitor",
    "electrolytic": "capacitor_polarized", "polarized": "capacitor_polarized",
    "led": "led", "diode": "diode", "button": "button", "switch": "button",
    "regulator": "regulator_3v3", "ldo": "regulator_3v3", "ams1117": "regulator_3v3",
    "usb": "usb_c", "usb-c": "usb_c", "usbc": "usb_c", "header": "header_1x4",
}


def handle(design: Design, message: str) -> tuple[Design, str, bool]:
    """Return (design, reply, should_build)."""
    msg = message.strip()
    low = msg.lower()

    if not low:
        return design, "Say something — try `help`.", False

    if low in ("help", "?", "/help"):
        return design, _HELP, False

    # build / route
    if re.fullmatch(r"(build|route|compile|make( it)?|generate|go)\b.*", low):
        return design, "Building netlist, board, and DRC…", True

    # new design
    m = re.match(r"(new|create|start)\s+(design\s+)?(?P<name>[\w-]+)", low)
    if m:
        return Design(name=m.group("name")), f"Started a new design **{m.group('name')}**.", False

    # load example
    m = re.match(r"(load|open|use|show)\s+(?P<what>.+)", low)
    if m:
        return _load(m.group("what").strip())
    # bare example keyword
    if low in EXAMPLES or low in _EXAMPLE_ALIASES:
        return _load(low)

    # connect
    m = re.match(r"(connect|wire|net|tie)\s+(?P<net>[\w+.\-]+)\s+(?P<rest>.+)", low)
    if m:
        return _connect(design, m.group("net"), m.group("rest"))

    # remove
    m = re.match(r"(remove|delete|rm)\s+(?P<ref>[a-z]+\d+)", low)
    if m:
        ref = m.group("ref").upper()
        design.remove_component(ref)
        return design, f"Removed {ref}.", False

    # add component(s)
    if low.startswith(("add", "place", "put", "drop")):
        return _add(design, msg)

    return design, ("I didn't catch that. Try `help`, `load usb`, "
                    "`add a 330 resistor`, `connect gnd u1.gnd c1.-`, or `build`."), False


def _load(what: str) -> tuple[Design, str, bool]:
    key = _EXAMPLE_ALIASES.get(what, what)
    if key not in EXAMPLES:
        return Design(), (f"Unknown example '{what}'. "
                          f"Have: {', '.join(EXAMPLES)}."), False
    d = build_example(key)
    return d, f"Loaded **{d.name}**. {d.notes} Type `build` to make it real.", True


_VALUE_RE = re.compile(r"\b(\d+(?:\.\d+)?\s?(?:k|m|u|n|p|µ)?(?:ohm|f|r)?)\b", re.I)


def _add(design: Design, msg: str) -> tuple[Design, str, bool]:
    low = msg.lower()
    # find a part type word
    type_key = None
    for word, key in _TYPE_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            type_key = key
            break
    if not type_key:
        return design, ("What part? e.g. `add resistor 330`, `add led`, "
                        "`add regulator`."), False
    # explicit ref like R1 / U2
    refm = re.search(r"\b([a-z]+)(\d+)\b", msg, re.I)
    ref = (refm.group(0).upper() if refm and refm.group(1).lower()
           not in ("k", "m", "u", "n", "p") else None)
    # value: a token with a unit-ish shape, excluding the ref
    value = ""
    for tok in _VALUE_RE.findall(msg):
        if ref and tok.upper().replace(" ", "") == ref:
            continue
        value = tok.replace(" ", "")
        break
    try:
        comp = design.add_component(type_key, ref=ref, value=value)
    except Exception as exc:
        return design, f"Couldn't add that: {exc}", False
    return design, (f"Added **{comp.ref}** ({comp.type}"
                    f"{' ' + comp.value if comp.value else ''})."), False


def _connect(design: Design, net: str, rest: str) -> tuple[Design, str, bool]:
    pins = re.split(r"[\s,]+", rest.strip())
    pins = [p for p in pins if "." in p]
    pins = [f"{p.split('.')[0].upper()}.{p.split('.')[1]}" for p in pins]
    if len(pins) < 1:
        return design, "Give pins as REF.PIN, e.g. `connect vcc r1.1 u1.vin`.", False
    try:
        design.connect(net.upper(), *pins)
    except Exception as exc:
        return design, f"Connect failed: {exc}", False
    return design, f"Connected {', '.join(pins)} → **{net.upper()}**.", False


_HELP = """**Commands**
- `load usb` / `load led` / `load divider` — load an example
- `new myboard` — start an empty design
- `add resistor 330` · `add led` · `add regulator` · `add usb` — add a part
- `connect <net> <ref.pin> <ref.pin> …` — wire a net (e.g. `connect gnd u1.gnd c1.-`)
- `remove R1` — delete a part
- `build` — generate netlist + board + run ERC/DRC

Tip: the full AI experience runs through the **MCP server** with Claude Code."""
