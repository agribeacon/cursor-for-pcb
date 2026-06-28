"""SPICE simulation — the deepest validation layer: actually *run* the circuit.

The review checks structure; ``electrical.py`` checks values in closed form;
this builds a real SPICE netlist from the design, runs **ngspice**, and reads
back the operating point — node voltages and branch currents — to verify the
circuit behaves. It is the "AI draws it, the machine runs it, wrong = fail" gate.

Scope is deliberately small but solid: DC power inputs (header / USB-C VBUS),
resistors, capacitors, LEDs (diode model), and linear regulators (modelled as
an ideal source on their output). That covers the boards this tool builds; an
unsupported part is skipped, never faked.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import electrical
from .model import Design

# nominal input-rail voltages (what a bench supply / USB would provide)
INPUT_V = {"5V": 5.0, "+5V": 5.0, "VBUS": 5.0, "VIN": 5.0, "12V": 12.0,
           "VCC": 5.0, "VDD": 5.0, "3V3": 3.3, "+3V3": 3.3,
           "VBAT": 3.7, "VLIPO": 3.7}
REG_VOUT = {"regulator_3v3": 3.3, "reg_5v": 5.0, "reg_7805": 5.0}
GND_NAMES = {"GND", "GROUND", "AGND", "DGND", "VSS"}
LED_MODEL = ".model DLED D(IS=1e-20 N=1.9 RS=2)"   # ~2V red/green indicator
LED_VF = 2.0   # nominal LED forward drop (V) — below this it isn't being driven


def has_ngspice() -> bool:
    return shutil.which("ngspice") is not None


@dataclass
class SimFinding:
    severity: str
    code: str
    message: str


def _is_gnd(n: str) -> bool:
    return n.upper() in GND_NAMES


def _index(design: Design):
    pin_net, comp_nets = {}, {r: set() for r in design.components}
    for name, net in design.nets.items():
        for nd in net.nodes:
            pin_net[(nd.ref, nd.pin)] = name
            comp_nets.setdefault(nd.ref, set()).add(name)
    return pin_net, comp_nets


def _node_map(design: Design) -> dict[str, str]:
    """Map net names to SPICE nodes (GND→0, others→sanitized)."""
    nodes = {}
    i = 1
    for name in design.nets:
        if _is_gnd(name):
            nodes[name] = "0"
        else:
            nodes[name] = "n" + re.sub(r"[^A-Za-z0-9]", "_", name)
            i += 1
    return nodes


def build_deck(design: Design) -> tuple[str, dict]:
    """Return (spice_deck, meta). meta carries node map + element bookkeeping."""
    pin_net, comp_nets = _index(design)
    nodes = _node_map(design)

    def net_of(ref, pin):
        return pin_net.get((ref, pin))

    lines = ["* cursor-for-pcb auto-generated", LED_MODEL]
    sourced = set()    # rails already driven by a regulator output
    leds = []          # (ref, anode_net, cathode_net)
    resistors = []     # (ref, netA, netB, ohms)

    # regulators → ideal source on their output rail
    for ref, comp in design.components.items():
        if comp.type in REG_VOUT:
            vout = net_of(ref, "vout") or net_of(ref, "2")
            if vout and not _is_gnd(vout):
                lines.append(f"V{ref}_reg {nodes[vout]} 0 DC {REG_VOUT[comp.type]}")
                sourced.add(vout)

    # passive / active elements
    for ref, comp in design.components.items():
        nets = sorted(comp_nets.get(ref, set()))
        if comp.type == "resistor":
            r = electrical.parse_ohms(comp.value) or 1e3
            ns = [net_of(ref, "1"), net_of(ref, "2")]
            ns = [n for n in ns if n]
            if len(ns) == 2:
                lines.append(f"R{ref} {nodes[ns[0]]} {nodes[ns[1]]} {r:g}")
                resistors.append((ref, ns[0], ns[1], r))
        elif comp.type in ("capacitor", "capacitor_polarized"):
            ns = [net_of(ref, "1") or net_of(ref, "+"),
                  net_of(ref, "2") or net_of(ref, "-")]
            ns = [n for n in ns if n]
            if len(ns) == 2:
                lines.append(f"C{ref} {nodes[ns[0]]} {nodes[ns[1]]} 1u")
        elif comp.type == "led":
            a = net_of(ref, "a") or net_of(ref, "2")
            k = net_of(ref, "k") or net_of(ref, "1")
            if a and k:
                lines.append(f"D{ref} {nodes[a]} {nodes[k]} DLED")
                leds.append((ref, a, k))

    # power comes IN through a connector (header / USB / terminal). Each such
    # non-ground rail that a regulator isn't already driving gets a DC source.
    def is_connector(t):
        return t.startswith("header") or "usb" in t or t in (
            "screw_terminal", "barrel_jack")

    # only a power-named connector pin is an input (a header's SCL/SDA/GPIO
    # signal pins are connectors too, but they aren't power).
    input_rails = set()
    for ref, comp in design.components.items():
        if is_connector(comp.type):
            input_rails |= {n for n in comp_nets.get(ref, set())
                            if not _is_gnd(n) and n.upper() in INPUT_V}
    input_rails -= sourced

    for rail in sorted(input_rails):
        v = INPUT_V.get(rail.upper(), 5.0)   # default a bare supply to 5 V
        lines.append(f"V{re.sub(r'[^A-Za-z0-9]', '', rail)}_in {nodes[rail]} 0 DC {v}")

    lines += [".control", "op", "print all", ".endc", ".end"]
    meta = {"nodes": nodes, "leds": leds, "resistors": resistors,
            "input_rails": sorted(input_rails), "sourced": sorted(sourced),
            "has_source": bool(input_rails or sourced)}
    return "\n".join(lines), meta


_VAL_RE = re.compile(r"^([\w()#.\[\]@]+)\s*=\s*([-\d.eE+]+)")


def run(design: Design) -> dict:
    """Simulate and return {ok, voltages, findings}. Findings are physics
    verdicts read back from the actual operating point."""
    if not has_ngspice():
        return {"ok": False, "reason": "ngspice not installed", "findings": []}
    deck, meta = build_deck(design)
    with tempfile.TemporaryDirectory() as td:
        cir = Path(td) / "c.cir"
        cir.write_text(deck)
        res = subprocess.run(["ngspice", "-b", str(cir)],
                             capture_output=True, text=True, timeout=30)
    text = res.stdout + res.stderr
    volt = {}
    for line in text.splitlines():
        m = _VAL_RE.match(line.strip())
        if m:
            volt[m.group(1).lower()] = float(m.group(2))

    if "singular matrix" in text.lower() or not volt:
        return {"ok": False, "reason": "did not converge (floating node / no DC path)",
                "findings": [SimFinding("warn", "SIM",
                    "simulation did not converge — a node may have no DC path to GND")]}

    def vn(net):
        node = meta["nodes"].get(net)
        if node == "0":
            return 0.0
        return volt.get(f"v({node})".lower(), volt.get(node.lower()))

    findings: list[SimFinding] = []
    if not meta["has_source"]:
        return {"ok": True, "voltages": {n: vn(n) for n in design.nets},
                "findings": [SimFinding("info", "SIM",
                    "no power input found to simulate (add a header/USB or "
                    "regulator)")]}
    # LED currents from the simulated operating point (series-resistor drop)
    for ref, a, k in meta["leds"]:
        # the resistor in series shares the LED anode net
        sr = next((r for r in meta["resistors"] if a in (r[1], r[2])), None)
        if not sr:
            continue
        va, vb = vn(sr[1]), vn(sr[2])
        if va is None or vb is None:
            continue
        i_ma = abs(va - vb) / sr[3] * 1000
        supply_v = max(va, vb)
        if supply_v < LED_VF:
            # the LED isn't fed from an always-on rail — it's GPIO/firmware
            # driven, so its DC-off current says nothing about correctness.
            findings.append(SimFinding("info", f"SIM_LED:{ref}",
                f"{ref}: GPIO/firmware-driven LED (current depends on firmware)"))
        elif i_ma > 25:
            findings.append(SimFinding("error", f"SIM_LED:{ref}",
                f"{ref}: simulated LED current {i_ma:.0f} mA exceeds safe ~20 mA — will burn"))
        elif i_ma < 0.5:
            findings.append(SimFinding("warn", f"SIM_LED:{ref}",
                f"{ref}: simulated LED current {i_ma:.2f} mA — too low to light"))
        else:
            findings.append(SimFinding("ok", f"SIM_LED:{ref}",
                f"{ref}: simulated LED current {i_ma:.0f} mA ✓"))

    # total input current → rail-to-GND short detection
    iin = sum(abs(v) for k2, v in volt.items() if "_in" in k2 and "branch" in k2)
    if iin > 0.5:
        findings.append(SimFinding("error", "SIM_SHORT",
            f"input draws {iin*1000:.0f} mA — likely a rail-to-GND short"))

    return {"ok": True, "voltages": {n: vn(n) for n in design.nets},
            "findings": findings}
