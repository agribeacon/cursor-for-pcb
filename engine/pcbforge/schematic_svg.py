"""Render a :class:`~pcbforge.model.Design` to an EDA-style schematic SVG.

Not a full KiCad symbol engine, but a real schematic look: a dot grid, proper
component symbols (resistor / LED / diode / capacitor / inductor / crystal /
button, ICs & connectors as labelled boxes), power & ground *symbols* instead of
floating labels for power rails, and orthogonal wires for signal nets. Layout is
a left-to-right signal flow which suits the small boards this tool generates.
"""
from __future__ import annotations

from html import escape

from . import library
from .model import Design

# ---- theme ----------------------------------------------------------------
BG = "#0f1216"
GRID = "#1b2027"
WIRE = "#7d8aa0"
SYM = "#c8d3e6"        # symbol stroke
TEXT = "#e6edf7"
MUTED = "#7a869c"
REF = "#6cb6ff"        # reference designators
VAL = "#e8c07d"        # values (warm, not neon)
SIGCOL = ["#6cb6ff", "#a6da95", "#e0af68", "#c699e8", "#7ad1d1", "#f7768e"]
POWER_COL = "#f7768e"
GND_COL = "#8b97ab"

GND_NAMES = {"GND", "GROUND", "AGND", "DGND", "VSS"}
POWER_NAMES = {"5V", "+5V", "3V3", "+3V3", "VCC", "VDD", "VBUS", "VIN", "12V"}


def _is_gnd(n):
    return n.upper() in GND_NAMES


def _is_power(n):
    return n.upper() in POWER_NAMES


# ---- symbols --------------------------------------------------------------
# each returns (svg, pins) where pins maps the friendly pin -> (x, y).
# symbols are drawn around a centre (cx, cy); body spans roughly 70px wide.

def _two_pin_pins(cx, cy, names):
    return {names[0]: (cx - 45, cy), names[1]: (cx + 45, cy)}


def _resistor(cx, cy, names):
    s = (f'<path d="M{cx-45},{cy} h17 '
         f'l4,-9 l8,18 l8,-18 l8,18 l8,-18 l4,9 h17" '
         f'fill="none" stroke="{SYM}" stroke-width="2" stroke-linejoin="round"/>')
    return s, _two_pin_pins(cx, cy, names)


def _capacitor(cx, cy, names, polar=False):
    s = (f'<line x1="{cx-45}" y1="{cy}" x2="{cx-6}" y2="{cy}" stroke="{SYM}" stroke-width="2"/>'
         f'<line x1="{cx-6}" y1="{cy-14}" x2="{cx-6}" y2="{cy+14}" stroke="{SYM}" stroke-width="2.5"/>'
         f'<line x1="{cx+45}" y1="{cy}" x2="{cx+6}" y2="{cy}" stroke="{SYM}" stroke-width="2"/>')
    if polar:
        s += (f'<path d="M{cx+6},{cy-14} q-8,14 0,28" fill="none" stroke="{SYM}" stroke-width="2.5"/>'
              f'<text x="{cx-18}" y="{cy-10}" fill="{MUTED}" font-size="12">+</text>')
    else:
        s += f'<line x1="{cx+6}" y1="{cy-14}" x2="{cx+6}" y2="{cy+14}" stroke="{SYM}" stroke-width="2.5"/>'
    return s, _two_pin_pins(cx, cy, names)


def _led(cx, cy, names):
    # anode (left) -> triangle -> cathode bar (right). names = [anode, cathode]
    s = (f'<line x1="{cx-45}" y1="{cy}" x2="{cx-12}" y2="{cy}" stroke="{SYM}" stroke-width="2"/>'
         f'<line x1="{cx+45}" y1="{cy}" x2="{cx+12}" y2="{cy}" stroke="{SYM}" stroke-width="2"/>'
         f'<path d="M{cx-12},{cy-13} L{cx-12},{cy+13} L{cx+12},{cy} Z" '
         f'fill="none" stroke="{SYM}" stroke-width="2" stroke-linejoin="round"/>'
         f'<line x1="{cx+12}" y1="{cy-13}" x2="{cx+12}" y2="{cy+13}" stroke="{SYM}" stroke-width="2.5"/>'
         # emission arrows
         f'<path d="M{cx+2},{cy-16} l8,-8 M{cx+10},{cy-24} l-2,5 l5,-2" stroke="{VAL}" stroke-width="1.5" fill="none"/>'
         f'<path d="M{cx+10},{cy-12} l8,-8 M{cx+18},{cy-20} l-2,5 l5,-2" stroke="{VAL}" stroke-width="1.5" fill="none"/>')
    pins = {names[0]: (cx - 45, cy), names[1]: (cx + 45, cy)}
    return s, pins


def _diode(cx, cy, names):
    s = (f'<line x1="{cx-45}" y1="{cy}" x2="{cx-12}" y2="{cy}" stroke="{SYM}" stroke-width="2"/>'
         f'<line x1="{cx+45}" y1="{cy}" x2="{cx+12}" y2="{cy}" stroke="{SYM}" stroke-width="2"/>'
         f'<path d="M{cx-12},{cy-13} L{cx-12},{cy+13} L{cx+12},{cy} Z" '
         f'fill="none" stroke="{SYM}" stroke-width="2" stroke-linejoin="round"/>'
         f'<line x1="{cx+12}" y1="{cy-13}" x2="{cx+12}" y2="{cy+13}" stroke="{SYM}" stroke-width="2.5"/>')
    return s, _two_pin_pins(cx, cy, names)


def _inductor(cx, cy, names):
    s = (f'<line x1="{cx-45}" y1="{cy}" x2="{cx-30}" y2="{cy}" stroke="{SYM}" stroke-width="2"/>'
         f'<path d="M{cx-30},{cy} a7,7 0 0 1 14,0 a7,7 0 0 1 14,0 a7,7 0 0 1 14,0 a7,7 0 0 1 14,0" '
         f'fill="none" stroke="{SYM}" stroke-width="2"/>'
         f'<line x1="{cx+26}" y1="{cy}" x2="{cx+45}" y2="{cy}" stroke="{SYM}" stroke-width="2"/>')
    return s, _two_pin_pins(cx, cy, names)


def _button(cx, cy, names):
    s = (f'<line x1="{cx-45}" y1="{cy}" x2="{cx-14}" y2="{cy}" stroke="{SYM}" stroke-width="2"/>'
         f'<line x1="{cx+45}" y1="{cy}" x2="{cx+14}" y2="{cy}" stroke="{SYM}" stroke-width="2"/>'
         f'<circle cx="{cx-14}" cy="{cy}" r="2.5" fill="{SYM}"/>'
         f'<circle cx="{cx+14}" cy="{cy}" r="2.5" fill="{SYM}"/>'
         f'<line x1="{cx-16}" y1="{cy-12}" x2="{cx+16}" y2="{cy-12}" stroke="{SYM}" stroke-width="2"/>'
         f'<line x1="{cx}" y1="{cy-12}" x2="{cx}" y2="{cy-20}" stroke="{SYM}" stroke-width="2"/>')
    return s, _two_pin_pins(cx, cy, names)


_SYMBOLS = {
    "resistor": _resistor, "led": _led, "diode": _diode,
    "inductor": _inductor, "button": _button,
}


def _symbol(comp_type, cx, cy, pin_names):
    """Return (svg, pins) for a 2-pin symbol, or None to fall back to a box."""
    if comp_type == "resistor":
        return _resistor(cx, cy, pin_names)
    if comp_type == "led":
        return _led(cx, cy, pin_names)
    if comp_type == "diode":
        return _diode(cx, cy, pin_names)
    if comp_type == "inductor":
        return _inductor(cx, cy, pin_names)
    if comp_type == "button":
        return _button(cx, cy, pin_names)
    if comp_type == "capacitor":
        return _capacitor(cx, cy, pin_names)
    if comp_type == "capacitor_polarized":
        return _capacitor(cx, cy, pin_names, polar=True)
    return None


def _gnd_symbol(x, y, down=True):
    d = 1 if down else -1
    return (f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y+18*d}" stroke="{GND_COL}" stroke-width="2"/>'
            f'<line x1="{x-10}" y1="{y+18*d}" x2="{x+10}" y2="{y+18*d}" stroke="{GND_COL}" stroke-width="2"/>'
            f'<line x1="{x-6}" y1="{y+22*d}" x2="{x+6}" y2="{y+22*d}" stroke="{GND_COL}" stroke-width="2"/>'
            f'<line x1="{x-2}" y1="{y+26*d}" x2="{x+2}" y2="{y+26*d}" stroke="{GND_COL}" stroke-width="2"/>')


def _power_symbol(x, y, name, up=True):
    d = -1 if up else 1
    ty = y + 30 * d
    return (f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y+16*d}" stroke="{POWER_COL}" stroke-width="2"/>'
            f'<line x1="{x-10}" y1="{y+16*d}" x2="{x+10}" y2="{y+16*d}" stroke="{POWER_COL}" stroke-width="2.5"/>'
            f'<text x="{x}" y="{ty}" fill="{POWER_COL}" font-size="11" font-weight="600" '
            f'text-anchor="middle">{escape(name)}</text>')


# ---- main -----------------------------------------------------------------
def render(design: Design, cols: int = 4) -> str:
    nets = design.nets
    # pin -> net, and net -> pins
    pin_net: dict[tuple, str] = {}
    for name, net in nets.items():
        for nd in net.nodes:
            pin_net[(nd.ref, nd.pin)] = name

    signal_nets = [n for n in nets if not _is_gnd(n) and not _is_power(n)]
    sig_color = {n: SIGCOL[i % len(SIGCOL)] for i, n in enumerate(signal_nets)}

    slot_w, slot_h = 200, 150
    pad = 50
    items = list(design.components.items())
    n = len(items)
    cols = min(cols, n) or 1
    rows = (n + cols - 1) // cols
    width = pad * 2 + cols * slot_w
    height = pad * 2 + rows * slot_h + 30

    out: list[str] = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
               f'viewBox="0 0 {width} {height}" font-family="ui-monospace, Menlo, monospace">')
    # background + dot grid
    out.append(f'<rect width="{width}" height="{height}" fill="{BG}"/>')
    out.append(f'<defs><pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">'
               f'<circle cx="1" cy="1" r="1" fill="{GRID}"/></pattern></defs>')
    out.append(f'<rect width="{width}" height="{height}" fill="url(#grid)"/>')
    out.append(f'<text x="{pad}" y="32" fill="{TEXT}" font-size="15" font-weight="700">'
               f'{escape(design.name)}</text>')

    # place components, collect pin coordinates. Each component is wrapped in a
    # <g data-ref="..."> and each net's elements in <g data-net="..."> so the UI
    # can hover/click-highlight.
    pin_xy: dict[tuple, tuple] = {}
    body: list[str] = []
    for idx, (ref, comp) in enumerate(items):
        c, r = idx % cols, idx // cols
        cx = pad + c * slot_w + slot_w // 2
        cy = pad + 30 + r * slot_h + slot_h // 2
        pt = library.resolve(comp.type)
        pins_used = [p for (rf, p) in pin_net if rf == ref]
        g = [f'<g class="comp" data-ref="{escape(ref)}">']
        sym = _symbol(comp.type, cx, cy, pins_used[:2]) if len(pins_used) == 2 else None
        if sym:
            svg, pins = sym
            g.append(svg)
            g.append(f'<text x="{cx}" y="{cy-26}" fill="{REF}" font-size="13" '
                     f'font-weight="700" text-anchor="middle">{escape(ref)}</text>')
            if comp.value:
                g.append(f'<text x="{cx}" y="{cy+34}" fill="{VAL}" font-size="12" '
                         f'text-anchor="middle">{escape(comp.value)}</text>')
            for p, xy in pins.items():
                pin_xy[(ref, p)] = xy
        else:
            np = max(len(pins_used), 1)
            bh = max(70, 22 + ((np + 1) // 2) * 22)
            bw = 92
            x0, y0 = cx - bw // 2, cy - bh // 2
            g.append(f'<rect x="{x0}" y="{y0}" width="{bw}" height="{bh}" rx="6" '
                     f'fill="#161b22" stroke="{SYM}" stroke-width="1.5"/>')
            g.append(f'<text x="{cx}" y="{y0+18}" fill="{REF}" font-size="13" '
                     f'font-weight="700" text-anchor="middle">{escape(ref)}</text>')
            sub = comp.value or pt.key
            g.append(f'<text x="{cx}" y="{y0+33}" fill="{MUTED}" font-size="9.5" '
                     f'text-anchor="middle">{escape(sub[:14])}</text>')
            for pidx, p in enumerate(pins_used):
                left = pidx % 2 == 0
                py = y0 + 44 + (pidx // 2) * 20
                px = x0 if left else x0 + bw
                xo = px - 16 if left else px + 16
                g.append(f'<line x1="{px}" y1="{py}" x2="{xo}" y2="{py}" stroke="{WIRE}" stroke-width="1.5"/>')
                g.append(f'<text x="{px + (5 if left else -5)}" y="{py-3}" fill="{MUTED}" '
                         f'font-size="8" text-anchor="{"start" if left else "end"}">{escape(p)}</text>')
                pin_xy[(ref, p)] = (xo, py)
        g.append('</g>')
        body.append("".join(g))

    # power / ground symbols at their pins (tagged by net for highlighting)
    for (ref, p), net in pin_net.items():
        if (ref, p) not in pin_xy:
            continue
        x, y = pin_xy[(ref, p)]
        if _is_gnd(net):
            out.append(f'<g class="net" data-net="{escape(net)}">{_gnd_symbol(x, y, down=True)}</g>')
        elif _is_power(net):
            out.append(f'<g class="net" data-net="{escape(net)}">{_power_symbol(x, y, net, up=True)}</g>')

    out.extend(body)

    # signal wires (orthogonal) — connect each signal net's pins through a bus y
    for net in signal_nets:
        pts = [pin_xy[(nd.ref, nd.pin)] for nd in nets[net].nodes if (nd.ref, nd.pin) in pin_xy]
        if len(pts) < 2:
            continue
        col = sig_color[net]
        pts.sort()
        bus_y = min(p[1] for p in pts) - 26
        xs = [p[0] for p in pts]
        w = [f'<g class="net" data-net="{escape(net)}">']
        w.append(f'<line x1="{min(xs)}" y1="{bus_y}" x2="{max(xs)}" y2="{bus_y}" '
                 f'stroke="{col}" stroke-width="2"/>')
        for (x, y) in pts:
            w.append(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{bus_y}" stroke="{col}" stroke-width="2"/>')
            w.append(f'<circle cx="{x}" cy="{y}" r="2.5" fill="{col}"/>')
        mx = (min(xs) + max(xs)) // 2
        tw = len(net) * 6.6 + 10
        w.append(f'<rect x="{mx-tw/2:.0f}" y="{bus_y-17}" width="{tw:.0f}" height="14" rx="4" '
                 f'fill="{BG}" stroke="{col}" stroke-width="1"/>')
        w.append(f'<text x="{mx}" y="{bus_y-6}" fill="{col}" font-size="10.5" '
                 f'text-anchor="middle">{escape(net)}</text>')
        w.append('</g>')
        out.append("".join(w))

    out.append("</svg>")
    return "\n".join(out)
