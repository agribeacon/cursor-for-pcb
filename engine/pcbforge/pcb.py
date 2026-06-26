"""Author a real ``.kicad_pcb`` from a :class:`~pcbforge.model.Design`.

We don't have KiCad's ``pcbnew`` Python module in a plain venv, so instead of
driving the GUI engine we build the board file directly with kiutils:

  * load each component's footprint from the stock KiCad libraries,
  * place them on a grid sized to each part's real courtyard so silkscreen and
    courtyards don't collide,
  * assign nets to every pad (power pins fan out to all their pads),
  * draw an Edge.Cuts board outline,
  * optionally autoroute copper (see :mod:`pcbforge.route`).

The result opens in KiCad and renders/DRCs through ``kicad-cli``.
"""
from __future__ import annotations

import math
from pathlib import Path

from . import kicad_env, library, route as _route
from .model import Design


def _load_footprint(lib_id: str):
    from kiutils.footprint import Footprint
    path = kicad_env.footprint_path(lib_id)
    if not path.exists():
        raise FileNotFoundError(f"Footprint not found: {lib_id} ({path})")
    fp = Footprint.from_file(str(path))
    lib, name = lib_id.split(":", 1)
    fp.libraryNickname = lib
    fp.entryName = name
    return fp


def _set_text(fp, kind: str, value: str, hide: bool = False) -> None:
    """Set the Reference/Value of a loaded footprint across kiutils versions.

    ``hide`` removes the text from silkscreen (we hide component values to keep
    the silk legible and avoid silk-over-pad DRC noise — KiCad's default too)."""
    try:
        if isinstance(fp.properties, dict):
            fp.properties[kind.capitalize()] = value
    except Exception:
        pass
    for item in getattr(fp, "graphicItems", []) or []:
        if getattr(item, "type", None) == kind.lower():
            item.text = value
            if hide and hasattr(item, "hide"):
                item.hide = True
        if getattr(item, "key", None) and item.key.lower() == kind.lower():
            item.value = value


def _fp_bbox(fp) -> tuple[float, float, float, float]:
    """Footprint extent relative to its origin: (minx, miny, maxx, maxy).

    Considers pad copper plus silk/courtyard graphics so the placement grid
    accounts for the part's real footprint, not just its pads.
    """
    xs, ys = [], []
    for pad in fp.pads:
        px, py = (pad.position.X or 0), (pad.position.Y or 0)
        sx = (pad.size.X if pad.size else 0) / 2
        sy = (pad.size.Y if pad.size else 0) / 2
        xs += [px - sx, px + sx]
        ys += [py - sy, py + sy]
    for item in getattr(fp, "graphicItems", []) or []:
        for attr in ("start", "end", "center", "position"):
            p = getattr(item, attr, None)
            if p is not None and hasattr(p, "X"):
                xs.append(p.X); ys.append(p.Y)
    if not xs:
        return (-1, -1, 1, 1)
    return (min(xs), min(ys), max(xs), max(ys))


def build_board(design: Design, path: str | Path,
                columns: int | None = None, gap: float = 3.5,
                route: bool = True) -> dict:
    """Generate a board file. Returns a dict with the path + routing stats."""
    from kiutils.board import Board
    from kiutils.items.common import Net, Position
    from kiutils.items.gritems import GrRect

    kicad_env.setup()
    board = Board.create_new()

    # ---- nets: code 0 is the unconnected net by KiCad convention --------
    net_codes: dict[str, int] = {}
    board.nets = [Net(0, "")]
    for i, name in enumerate(design.nets.keys(), start=1):
        net_codes[name] = i
        board.nets.append(Net(i, name))

    # pad (ref, pad_number) -> (net_code, net_name); power pins fan out
    pad_net: dict[tuple[str, str], tuple[int, str]] = {}
    for name, net in design.nets.items():
        for node in net.nodes:
            pt = library.resolve(design.components[node.ref].type)
            for pad_no in library.pin_numbers(pt, node.pin):
                pad_net[(node.ref, pad_no)] = (net_codes[name], name)

    # ---- load footprints + measure them --------------------------------
    loaded = []
    cell_w = cell_h = 1.0
    for ref, comp in design.components.items():
        fp = _load_footprint(comp.resolved_footprint())
        bx0, by0, bx1, by1 = _fp_bbox(fp)
        loaded.append((ref, comp, fp, (bx0, by0, bx1, by1)))
        cell_w = max(cell_w, bx1 - bx0)
        cell_h = max(cell_h, by1 - by0)
    cell_w += gap
    cell_h += gap

    # ---- place on a uniform grid, each part centred in its cell ---------
    n = len(loaded)
    cols = columns or max(1, math.ceil(math.sqrt(n)))
    margin = 8.0
    cxs, cys = [], []
    for idx, (ref, comp, fp, (bx0, by0, bx1, by1)) in enumerate(loaded):
        col, row = idx % cols, idx // cols
        cell_cx = margin + col * cell_w + cell_w / 2
        cell_cy = margin + row * cell_h + cell_h / 2
        # shift so the footprint bbox centre lands on the cell centre
        bcx, bcy = (bx0 + bx1) / 2, (by0 + by1) / 2
        fp.position = Position(X=round(cell_cx - bcx, 3),
                               Y=round(cell_cy - bcy, 3))
        _set_text(fp, "reference", ref)
        _set_text(fp, "value", comp.value, hide=True)
        for pad in fp.pads:
            key = (ref, str(pad.number))
            if key in pad_net:
                code, nname = pad_net[key]
                pad.net = Net(code, nname)
        board.footprints.append(fp)
        cxs.append(cell_cx); cys.append(cell_cy)

    # ---- board outline (Edge.Cuts rectangle) ---------------------------
    if cxs:
        x0 = margin - gap
        y0 = margin - gap
        x1 = max(cxs) + cell_w / 2 + gap
        y1 = max(cys) + cell_h / 2 + gap
    else:
        x0, y0, x1, y1 = 0, 0, 40, 30
    board.graphicItems.append(GrRect(
        start=Position(X=round(x0, 3), Y=round(y0, 3)),
        end=Position(X=round(x1, 3), Y=round(y1, 3)),
        layer="Edge.Cuts", width=0.15))

    stats = {}
    if route:
        stats = _route.route_board(board)

    path = Path(path)
    board.to_file(str(path))
    return {"path": str(path), "route": stats}
