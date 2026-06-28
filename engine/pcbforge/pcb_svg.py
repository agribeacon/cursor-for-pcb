"""Render a built .kicad_pcb to a readable, fab-looking SVG.

kicad-cli's own SVG is just colored copper with no labels. This renderer reads
the board geometry (pads, traces, vias, footprint silk, board outline) and adds
what makes a PCB *readable*: reference designators (J1/R1/D1) placed clearly,
component outlines + polarity markers (from the footprint silkscreen), a pin-1
marker, top/bottom copper distinguished by color, and the board dimensions.
"""
from __future__ import annotations

import math
from html import escape

from .model import Design

BG = "#0b0e13"
BOARD = "#10302a"          # substrate (PCB green-ish, muted)
EDGE = "#e8d27a"
FCU = "#d9774a"            # top copper
BCU = "#4f8fd9"            # bottom copper
PAD_F = "#f0a878"
PAD_B = "#7fb0e8"
SILK = "#c4ccd8"
REFC = "#ffffff"
DIM = "#8a93a3"


def _rot(px, py, ang):
    if not ang:
        return px, py
    a = math.radians(ang)
    return px * math.cos(a) - py * math.sin(a), px * math.sin(a) + py * math.cos(a)


def render(pcb_path, design: Design | None = None) -> str:
    from kiutils.board import Board
    b = Board.from_file(str(pcb_path))

    # board outline bounds from Edge.Cuts
    xs, ys = [], []
    edges = []
    for g in b.graphicItems:
        if getattr(g, "layer", "") == "Edge.Cuts" and hasattr(g, "start"):
            edges.append((g.start.X, g.start.Y, g.end.X, g.end.Y))
            xs += [g.start.X, g.end.X]; ys += [g.start.Y, g.end.Y]
    if not xs:
        xs, ys = [0, 40], [0, 30]
    minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)
    bw, bh = maxx - minx, maxy - miny
    pad = 6
    W = (bw + pad * 2)
    H = (bh + pad * 2) + 10
    sc = 14  # px per mm
    def X(x): return (x - minx + pad) * sc
    def Y(y): return (y - miny + pad) * sc

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W*sc:.0f}" height="{H*sc:.0f}" '
           f'viewBox="0 0 {W*sc:.0f} {H*sc:.0f}" font-family="ui-monospace,Menlo,monospace">']
    out.append(f'<rect width="{W*sc:.0f}" height="{H*sc:.0f}" fill="{BG}"/>')
    # board substrate
    out.append(f'<rect x="{X(minx):.0f}" y="{Y(miny):.0f}" width="{bw*sc:.0f}" '
               f'height="{bh*sc:.0f}" rx="6" fill="{BOARD}" stroke="{EDGE}" stroke-width="2"/>')

    types = {c.ref: c.type for c in design.components.values()} if design else {}

    # --- copper traces (bottom first, then top) ---
    for layer, col in (("B.Cu", BCU), ("F.Cu", FCU)):
        for t in (b.traceItems or []):
            if type(t).__name__ == "Segment" and t.layer == layer:
                out.append(f'<line x1="{X(t.start.X):.1f}" y1="{Y(t.start.Y):.1f}" '
                           f'x2="{X(t.end.X):.1f}" y2="{Y(t.end.Y):.1f}" stroke="{col}" '
                           f'stroke-width="{max(1.5,t.width*sc):.1f}" stroke-linecap="round"/>')
    # vias
    for t in (b.traceItems or []):
        if type(t).__name__ == "Via":
            out.append(f'<circle cx="{X(t.position.X):.1f}" cy="{Y(t.position.Y):.1f}" '
                       f'r="{(getattr(t,"size",0.6)/2)*sc:.1f}" fill="#cfd6e0"/>')

    # --- footprints: silk outline + pads + ref ---
    for fp in b.footprints:
        ox, oy = fp.position.X, fp.position.Y
        ang = getattr(fp.position, "angle", 0) or 0
        ref = None
        try:
            ref = fp.properties.get("Reference") if isinstance(fp.properties, dict) else None
        except Exception:
            pass
        ref = ref or fp.entryName
        pxs, pys = [], []
        # silk (component outline + polarity markers)
        g = ['<g>']
        for it in (fp.graphicItems or []):
            if getattr(it, "layer", "") != "F.SilkS":
                continue
            if hasattr(it, "start") and hasattr(it, "end") and type(it).__name__ in ("FpLine", "FpRect"):
                sx, sy = _rot(it.start.X, it.start.Y, ang)
                ex, ey = _rot(it.end.X, it.end.Y, ang)
                if type(it).__name__ == "FpRect":
                    g.append(f'<rect x="{X(ox+min(sx,ex)):.1f}" y="{Y(oy+min(sy,ey)):.1f}" '
                             f'width="{abs(ex-sx)*sc:.1f}" height="{abs(ey-sy)*sc:.1f}" '
                             f'fill="none" stroke="{SILK}" stroke-width="1"/>')
                else:
                    g.append(f'<line x1="{X(ox+sx):.1f}" y1="{Y(oy+sy):.1f}" '
                             f'x2="{X(ox+ex):.1f}" y2="{Y(oy+ey):.1f}" stroke="{SILK}" stroke-width="1"/>')
        # pads
        for p in fp.pads:
            prx, pry = _rot(p.position.X or 0, p.position.Y or 0, ang)
            ax, ay = ox + prx, oy + pry
            pxs.append(ax); pys.append(ay)
            w, h = (p.size.X or 1), (p.size.Y or 1)
            bottom = "B.Cu" in (p.layers or []) and "*.Cu" not in (p.layers or [])
            col = PAD_B if bottom else PAD_F
            is1 = str(p.number) == "1"
            shape = (p.shape or "roundrect")
            if shape in ("circle", "oval") and abs(w-h) < 0.05:
                g.append(f'<circle cx="{X(ax):.1f}" cy="{Y(ay):.1f}" r="{w/2*sc:.1f}" fill="{col}"/>')
            else:
                g.append(f'<rect x="{X(ax-w/2):.1f}" y="{Y(ay-h/2):.1f}" width="{w*sc:.1f}" '
                         f'height="{h*sc:.1f}" rx="{0 if is1 else 2}" fill="{col}"/>')
            if is1:  # pin-1 marker
                g.append(f'<circle cx="{X(ax):.1f}" cy="{Y(ay):.1f}" r="1.3" fill="{BG}"/>')
            if p.type == "thru_hole":
                g.append(f'<circle cx="{X(ax):.1f}" cy="{Y(ay):.1f}" r="{min(w,h)/4*sc:.1f}" fill="{BOARD}"/>')
        # LED/diode polarity: bar on the cathode side label
        # reference designator above the part
        if pxs:
            cx = X(sum(pxs)/len(pxs))
            topy = Y(min(pys)) - 6
            g.append(f'<text x="{cx:.0f}" y="{topy:.0f}" fill="{REFC}" font-size="12" '
                     f'font-weight="700" text-anchor="middle">{escape(ref)}</text>')
            ty = types.get(ref, "")
            if ty in ("led", "diode"):
                g.append(f'<text x="{cx:.0f}" y="{Y(max(pys))+14:.0f}" fill="{DIM}" '
                         f'font-size="8" text-anchor="middle">▸|K</text>')
        g.append('</g>')
        out.append("".join(g))

    # board dimensions label
    out.append(f'<text x="{X(minx):.0f}" y="{Y(maxy)+16:.0f}" fill="{DIM}" font-size="10">'
               f'{bw:.1f} × {bh:.1f} mm · 2-layer</text>')
    # layer legend
    lx = X(maxx) - 120
    out.append(f'<rect x="{lx}" y="{Y(maxy)+8}" width="10" height="10" fill="{FCU}"/>'
               f'<text x="{lx+14}" y="{Y(maxy)+17}" fill="{DIM}" font-size="10">top</text>'
               f'<rect x="{lx+50}" y="{Y(maxy)+8}" width="10" height="10" fill="{BCU}"/>'
               f'<text x="{lx+64}" y="{Y(maxy)+17}" fill="{DIM}" font-size="10">bottom</text>')
    out.append("</svg>")
    return "\n".join(out)
