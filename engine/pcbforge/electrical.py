"""Analytical electrical sanity checks — physics, not just topology.

The design review checks *structure* ("does the LED have a series resistor?").
This module checks *values* with real physics ("is that resistor the right value,
or will it burn the LED / overheat?"). It's the circuit-specific equivalent of a
linter that actually evaluates expressions, not just their shape — and it's how
we catch an AI that wired a plausible-looking but electrically-wrong circuit.

No SPICE needed for these: they're closed-form (Ohm's law, P = I²R). A full
SPICE simulation (ngspice) would generalise this to arbitrary topologies; these
cover the common value mistakes on the circuits we support.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Design

# Nominal rail voltages (V) by net name. Unknown rails are skipped.
RAIL_V = {"5V": 5.0, "+5V": 5.0, "VBUS": 5.0, "VIN": 5.0,
          "3V3": 3.3, "+3V3": 3.3, "VDD": 3.3, "VDDA": 3.3, "VCC": 5.0}
LED_VF = 2.0          # forward drop (V) — red/green ≈ 2.0, conservative
LED_I_MAX = 25.0      # mA — above this most indicator LEDs cook
LED_I_MIN = 0.5       # mA — below this it's basically off
R0805_P = 0.125       # W — power rating of an 0805 resistor

_MULT = {"": 1, "r": 1, "k": 1e3, "m": 1e6, "meg": 1e6}


def parse_ohms(s: str) -> float | None:
    """'330'→330, '5.1k'→5100, '1M'→1e6, '4k7'→4700. None if unparseable."""
    if not s:
        return None
    t = s.strip().lower().replace("ω", "").replace("ohm", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(meg|[rkm])?", t)
    if m:
        return float(m.group(1)) * _MULT.get(m.group(2) or "", 1)
    # '4k7' style (R/k/M as decimal point)
    m = re.fullmatch(r"(\d+)([rkm])(\d+)", t)
    if m:
        return (float(m.group(1)) + float("0." + m.group(3))) * _MULT[m.group(2)]
    return None


@dataclass
class Finding:
    severity: str
    code: str
    message: str


def _index(design: Design):
    pin_net, comp_nets = {}, {r: set() for r in design.components}
    for name, net in design.nets.items():
        for n in net.nodes:
            pin_net[(n.ref, n.pin)] = name
            comp_nets.setdefault(n.ref, set()).add(name)
    return pin_net, comp_nets


def check(design: Design) -> list[Finding]:
    """Return electrical (value-level) findings."""
    out: list[Finding] = []
    pin_net, comp_nets = _index(design)

    def is_gnd(n):
        return n and n.upper() in ("GND", "GROUND", "AGND", "DGND", "VSS")

    # ---- LED current (Ohm's law) + series-resistor power ----------------
    for ref, comp in design.components.items():
        if comp.type != "led":
            continue
        nets = comp_nets.get(ref, set())
        nongnd = [n for n in nets if not is_gnd(n)]
        if not nongnd:
            continue
        anode_net = nongnd[0]
        # find the series resistor sharing the LED's anode net
        series_r = None
        for r, c in design.components.items():
            if c.type == "resistor" and anode_net in comp_nets.get(r, set()):
                series_r = (r, c)
                break
        if not series_r:
            continue
        rref, rc = series_r
        R = parse_ohms(rc.value)
        # the resistor's *other* net is the supply rail
        rail = next((n for n in comp_nets.get(rref, set()) if n != anode_net), None)
        v = RAIL_V.get((rail or "").upper())
        if not R or v is None:
            continue
        i_ma = max(0.0, (v - LED_VF) / R * 1000)
        if i_ma > LED_I_MAX:
            out.append(Finding("error", f"LED_I:{ref}",
                f"{ref}: LED current ≈ {i_ma:.0f} mA (>{LED_I_MAX:.0f} mA) — "
                f"{rc.value}Ω on {rail} will overdrive/burn the LED; use a larger resistor"))
        elif i_ma < LED_I_MIN:
            out.append(Finding("warn", f"LED_I:{ref}",
                f"{ref}: LED current ≈ {i_ma:.2f} mA — too low to light visibly; "
                f"use a smaller resistor"))
        else:
            out.append(Finding("ok", f"LED_I:{ref}",
                f"{ref}: LED current ≈ {i_ma:.0f} mA (safe), {rail}→{rc.value}Ω→LED"))
        # resistor power dissipation
        p = (i_ma / 1000) ** 2 * R
        if p > R0805_P:
            out.append(Finding("warn", f"RPWR:{rref}",
                f"{rref} dissipates ≈ {p*1000:.0f} mW (>{R0805_P*1000:.0f} mW for "
                f"0805) — use a larger package or higher resistance"))

    # ---- USB-C CC pulldown value (must be ~5.1k) -----------------------
    for ref, comp in design.components.items():
        if comp.type != "usb_c":
            continue
        for cc in ("cc1", "cc2"):
            net = pin_net.get((ref, cc))
            if not net or is_gnd(net):
                continue  # missing/shorted handled by the structural review
            for r, c in design.components.items():
                if c.type == "resistor" and net in comp_nets.get(r, set()):
                    R = parse_ohms(c.value)
                    if R and not (4500 <= R <= 5600):
                        out.append(Finding("warn", f"CCVAL:{ref}.{cc}",
                            f"{ref} {cc.upper()} pulldown is {c.value} — USB-C sink "
                            f"wants 5.1 kΩ (Rd)"))
    return out
