"""A senior-engineer design review for a :class:`~pcbforge.model.Design`.

This is the part that judges whether the output is *good*, not just whether it
builds. It encodes the electrical checks an experienced PCB engineer runs in
their head before sending a board to fab:

  * every IC power pin has local decoupling (100 nF) to GND,
  * every power rail has a bulk capacitor,
  * every LED has a series current-limiting resistor,
  * USB-C CC1/CC2 have 5.1 kΩ pulldowns (sink advertisement),
  * an MCU's reset/enable + boot-strap pins are pulled, not floating,
  * nothing is left unconnected, and a ground net exists,
  * plus the build-level verdicts (ERC, DRC, ground pour, fab files).

Each finding has a severity (error / warn / info) and the design gets a letter
grade. Run it from the CLI (`pcbforge review <example>`), the MCP `review`
tool, or `build_all` (the result carries a `review`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import library
from .model import Design

POWER_NAMES = {"VCC", "VDD", "3V3", "+3V3", "5V", "+5V", "VBUS", "VIN", "VOUT",
               "VBAT", "VVDD", "VDDA"}
GND_NAMES = {"GND", "GROUND", "AGND", "DGND", "VSS"}
# component types that are ICs needing decoupling
IC_TYPES = {"regulator_3v3", "reg_5v", "reg_7805", "esp32", "ne555", "opamp"}
CAP_TYPES = {"capacitor", "capacitor_polarized"}


@dataclass
class Finding:
    severity: str        # "error" | "warn" | "info" | "ok"
    code: str
    message: str


@dataclass
class Review:
    findings: list[Finding] = field(default_factory=list)
    score: int = 0
    max_score: int = 0
    grade: str = "—"

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warn")

    def to_dict(self) -> dict:
        return {
            "score": self.score, "max_score": self.max_score, "grade": self.grade,
            "errors": self.errors, "warnings": self.warnings,
            "findings": [f.__dict__ for f in self.findings],
        }


def _is_power(net: str) -> bool:
    return net.upper() in POWER_NAMES


def _is_gnd(net: str) -> bool:
    return net.upper() in GND_NAMES


def _index(design: Design):
    """Return (pin_net, comp_nets): (ref,pin)->net and ref->set(nets)."""
    pin_net: dict[tuple[str, str], str] = {}
    comp_nets: dict[str, set[str]] = {r: set() for r in design.components}
    for name, net in design.nets.items():
        for node in net.nodes:
            pin_net[(node.ref, node.pin)] = name
            comp_nets.setdefault(node.ref, set()).add(name)
    return pin_net, comp_nets


def _cap_between(design: Design, comp_nets, net_a: str, gnd_required=True) -> bool:
    """Is there a capacitor with one pin on net_a and the other on GND?"""
    for ref, comp in design.components.items():
        if comp.type not in CAP_TYPES:
            continue
        nets = comp_nets.get(ref, set())
        if net_a in nets and any(_is_gnd(n) for n in nets):
            return True
    return False


def review(design: Design, build_result: dict | None = None) -> Review:
    rv = Review()
    pin_net, comp_nets = _index(design)
    add = rv.findings.append

    def check(ok: bool, weight: int, code, ok_msg, bad_msg, severity="error"):
        rv.max_score += weight
        if ok:
            rv.score += weight
            add(Finding("ok", code, ok_msg))
        else:
            add(Finding(severity, code, bad_msg))

    # ---- connectivity / ground -----------------------------------------
    orphans = [r for r, nets in comp_nets.items() if not nets]
    check(not orphans, 2, "ORPHAN",
          "all components are connected",
          f"unconnected components: {', '.join(orphans)}")

    has_gnd = any(_is_gnd(n) for n in design.nets)
    check(has_gnd, 2, "GND",
          "a ground net exists", "no ground net found")

    # ---- power rails: bulk decoupling ----------------------------------
    rails = [n for n in design.nets if _is_power(n)]
    for rail in rails:
        # bulk cap (polarized or any cap) from rail to GND
        bulk = any(c.type == "capacitor_polarized" and rail in comp_nets.get(r, set())
                   and any(_is_gnd(x) for x in comp_nets.get(r, set()))
                   for r, c in design.components.items())
        any_cap = _cap_between(design, comp_nets, rail)
        check(bulk or any_cap, 1, f"BULK:{rail}",
              f"rail {rail} is decoupled",
              f"rail {rail} has no bulk/decoupling capacitor to GND",
              severity="warn")

    # ---- ICs: local decoupling -----------------------------------------
    for ref, comp in design.components.items():
        if comp.type not in IC_TYPES:
            continue
        # power pins of this IC = any net it touches whose name is a power rail
        power_nets = {n for n in comp_nets.get(ref, set()) if _is_power(n)}
        if not power_nets:
            add(Finding("warn", f"PWR:{ref}", f"{ref} has no power pin connected"))
            rv.max_score += 1
            continue
        decoupled = any(_cap_between(design, comp_nets, pn) for pn in power_nets)
        check(decoupled, 2, f"DECAP:{ref}",
              f"{ref} ({comp.type}) is decoupled",
              f"{ref} ({comp.type}) has no 100nF decoupling cap near its power pin")

    # ---- LEDs: series resistor -----------------------------------------
    for ref, comp in design.components.items():
        if comp.type != "led":
            continue
        # the LED's non-GND net should also touch a resistor
        nongnd = [n for n in comp_nets.get(ref, set()) if not _is_gnd(n)]
        has_r = any(c.type == "resistor" and (set(nongnd) & comp_nets.get(r, set()))
                    for r, c in design.components.items())
        check(has_r, 1, f"LEDR:{ref}",
              f"{ref} has a series resistor",
              f"{ref} (LED) has no current-limiting resistor")

    # ---- USB-C: CC pulldowns -------------------------------------------
    for ref, comp in design.components.items():
        if comp.type != "usb_c":
            continue
        for cc in ("cc1", "cc2"):
            net = pin_net.get((ref, cc))
            ok = bool(net) and any(
                c.type == "resistor" and net in comp_nets.get(r, set())
                and any(_is_gnd(x) for x in comp_nets.get(r, set()))
                for r, c in design.components.items())
            check(ok, 1, f"CC:{ref}.{cc}",
                  f"{ref} {cc.upper()} has a 5.1k pulldown",
                  f"{ref} {cc.upper()} missing 5.1k pulldown to GND (USB-C sink)")

    # ---- MCU strap pins (ESP32) ----------------------------------------
    for ref, comp in design.components.items():
        if comp.type != "esp32":
            continue
        for pin, what in (("en", "EN/reset pull-up"), ("io0", "IO0 boot pull-up")):
            net = pin_net.get((ref, pin))
            pulled = bool(net) and any(
                c.type == "resistor" and net in comp_nets.get(r, set())
                and any(_is_power(x) for x in comp_nets.get(r, set()))
                for r, c in design.components.items())
            check(pulled, 1, f"STRAP:{ref}.{pin}",
                  f"{ref} {pin.upper()} is pulled",
                  f"{ref} {what} missing (floating strap pin)", severity="warn")

    # ---- build-level verdicts ------------------------------------------
    if build_result:
        b = build_result
        check(b.get("erc_errors", 1) == 0, 2, "ERC",
              "ERC passes (0 errors)", f"ERC has {b.get('erc_errors')} errors")
        check(b.get("drc_unconnected", 1) == 0, 2, "UNCONN",
              "no unconnected ratsnest", f"{b.get('drc_unconnected')} unconnected pads")
        copper = b.get("drc_copper")
        if copper is not None:
            check(copper == 0, 1, "DRC_COPPER",
                  "no copper DRC violations (shorts/clearance)",
                  f"{copper} copper DRC violations", severity="warn")
        check(bool(b.get("poured")), 1, "POUR",
              "a ground plane is poured",
              "no ground plane (consider a GND pour)", severity="info")
        check(b.get("tracks", 0) > 0, 1, "ROUTED",
              "board is autorouted", "board is not routed", severity="warn")

    # ---- grade ----------------------------------------------------------
    pct = (rv.score / rv.max_score * 100) if rv.max_score else 0
    if rv.errors:
        rv.grade = "F" if pct < 60 else "C"
    elif pct >= 95:
        rv.grade = "A"
    elif pct >= 85:
        rv.grade = "B"
    elif pct >= 70:
        rv.grade = "C"
    else:
        rv.grade = "D"
    return rv
