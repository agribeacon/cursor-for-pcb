"""Render a :class:`~pcbforge.model.Design` to a clean schematic-style SVG.

This is *not* a KiCad schematic engine (no symbol graphics / wire autorouting).
It is a readable "flat netlist" view — each component is a labeled box with pin
stubs, and every pin carries a colored net-label tag. Engineers read these all
the time, and it renders deterministically with zero external dependencies,
which makes it perfect for a fast chat-driven UI.
"""
from __future__ import annotations

from html import escape

from . import library
from .model import Design

# A palette that stays legible on the dark UI in the mock-ups.
_PALETTE = [
    "#e06c75", "#61afef", "#98c379", "#e5c07b", "#c678dd",
    "#56b6c2", "#d19a66", "#abb2bf", "#be5046", "#528bff",
]
_POWER = {"GND": "#000000", "VBUS": "#e06c75", "VCC": "#e06c75",
          "5V": "#e06c75", "3V3": "#d19a66", "VIN": "#e06c75"}


def _net_color(name: str, idx: int) -> str:
    up = name.upper()
    for key, col in _POWER.items():
        if up == key:
            return col
    return _PALETTE[idx % len(_PALETTE)]


def render(design: Design, cols: int = 3) -> str:
    # net -> color
    net_color = {n: _net_color(n, i) for i, n in enumerate(design.nets.keys())}
    # ref -> ordered list of (friendly_pin, net_name) it connects to
    comp_pins: dict[str, list[tuple[str, str]]] = {r: [] for r in design.components}
    for name, net in design.nets.items():
        for node in net.nodes:
            comp_pins.setdefault(node.ref, []).append((node.pin, name))

    box_w, box_h = 150, 100
    # wide horizontal gap so the net-label tags on facing pins of adjacent
    # boxes (e.g. R1's right pin and D1's left pin on the same net) don't collide
    gap_x, gap_y = 260, 90
    pad = 40
    items = list(design.components.items())
    rows = (len(items) + cols - 1) // cols or 1
    width = pad * 2 + cols * box_w + (cols - 1) * gap_x
    height = pad * 2 + rows * box_h + (rows - 1) * gap_y + 60

    out: list[str] = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" '
        f'font-family="ui-monospace, Menlo, monospace">'
    )
    out.append(f'<rect width="{width}" height="{height}" fill="#1e2127"/>')
    out.append(f'<text x="{pad}" y="26" fill="#abb2bf" font-size="16" '
               f'font-weight="bold">{escape(design.name)}</text>')

    for idx, (ref, comp) in enumerate(items):
        col, row = idx % cols, idx // cols
        x = pad + col * (box_w + gap_x)
        y = pad + 30 + row * (box_h + gap_y)
        pt = library.resolve(comp.type)
        out.append(
            f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="8" '
            f'fill="#282c34" stroke="#4b5263" stroke-width="1.5"/>'
        )
        out.append(f'<text x="{x + box_w/2}" y="{y + 30}" fill="#e5e9f0" '
                   f'font-size="15" font-weight="bold" text-anchor="middle">'
                   f'{escape(ref)}</text>')
        out.append(f'<text x="{x + box_w/2}" y="{y + 50}" fill="#98c379" '
                   f'font-size="13" text-anchor="middle">{escape(comp.value)}</text>')
        out.append(f'<text x="{x + box_w/2}" y="{y + 68}" fill="#5c6370" '
                   f'font-size="10" text-anchor="middle">{escape(pt.key)}</text>')

        # one stub per net this component touches (net-centric, readable even
        # for many-pin parts like USB-C where one net spans several pads)
        stubs = comp_pins.get(ref, [])
        for pidx, (pin, net) in enumerate(stubs):
            left = pidx % 2 == 0
            py = y + 24 + (pidx // 2) * 22
            if py > y + box_h - 8:
                py = y + box_h - 8
            if left:
                sx0, sx1, tx, anc = x - 26, x, x - 30, "end"
            else:
                sx0, sx1, tx, anc = x + box_w, x + box_w + 26, x + box_w + 30, "start"
            col_line = net_color.get(net, "#3b4048")
            out.append(f'<line x1="{sx0}" y1="{py}" x2="{sx1}" y2="{py}" '
                       f'stroke="{col_line}" stroke-width="2"/>')
            out.append(f'<circle cx="{sx0 if left else sx1}" cy="{py}" r="3" '
                       f'fill="{col_line}"/>')
            # a solid pill behind the net tag so a label never reads as garbled
            # text even if it ends up near another one
            label = f"{net} {pin}"
            w = len(label) * 6.8 + 12
            rx = (tx - w + 4) if left else (tx - 4)
            out.append(f'<rect x="{rx:.0f}" y="{py - 9}" width="{w:.0f}" height="18" '
                       f'rx="5" fill="#21252b" stroke="{col_line}" '
                       f'stroke-width="1"/>')
            out.append(f'<text x="{tx}" y="{py + 4}" fill="{col_line}" '
                       f'font-size="11" text-anchor="{anc}">{escape(net)}'
                       f'<tspan fill="#7a8290"> {escape(pin)}</tspan></text>')

    # legend
    ly = height - 20
    lx = pad
    out.append(f'<text x="{lx}" y="{ly}" fill="#5c6370" font-size="11">nets:</text>')
    lx += 45
    for name, col in net_color.items():
        out.append(f'<rect x="{lx}" y="{ly-10}" width="12" height="12" rx="2" fill="{col}"/>')
        out.append(f'<text x="{lx+18}" y="{ly}" fill="#abb2bf" font-size="11">{escape(name)}</text>')
        lx += 40 + len(name) * 7
    out.append("</svg>")
    return "\n".join(out)
