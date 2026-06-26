"""Author a real ``.kicad_pcb`` from a :class:`~pcbforge.model.Design`.

We don't have KiCad's ``pcbnew`` Python module in a plain venv, so instead of
driving the GUI engine we build the board file directly with kiutils:

  * load each component's footprint from the stock KiCad libraries,
  * lay them out on a simple grid (a deterministic, conflict-free placement —
    not an autorouter, but a valid starting board),
  * assign nets to pads so the ratsnest is correct,
  * draw an Edge.Cuts rectangle as the board outline.

The result opens in KiCad and renders/DRCs through ``kicad-cli``.
"""
from __future__ import annotations

import math
from pathlib import Path

from . import kicad_env, library
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


def _set_text(fp, kind: str, value: str) -> None:
    """Set the Reference/Value of a loaded footprint across kiutils versions."""
    # property dict form
    try:
        if isinstance(fp.properties, dict):
            fp.properties[kind.capitalize()] = value
    except Exception:
        pass
    # fp_text graphic items
    for item in getattr(fp, "graphicItems", []) or []:
        if getattr(item, "type", None) == kind.lower():
            item.text = value
        # kiutils Property objects
        if getattr(item, "key", None) and item.key.lower() == kind.lower():
            item.value = value


def build_board(design: Design, path: str | Path,
                columns: int | None = None, pitch: float = 14.0) -> Path:
    """Generate a board file. ``pitch`` is grid spacing in mm."""
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

    # pad (ref, pin_number) -> (net_code, net_name)
    pad_net: dict[tuple[str, str], tuple[int, str]] = {}
    for name, net in design.nets.items():
        for node in net.nodes:
            pt = library.resolve(design.components[node.ref].type)
            pin_no = library.pin_number(pt, node.pin)
            pad_net[(node.ref, pin_no)] = (net_codes[name], name)

    # ---- place components on a grid ------------------------------------
    n = len(design.components)
    cols = columns or max(1, math.ceil(math.sqrt(n)))
    margin = 10.0
    xs, ys = [], []
    for idx, (ref, comp) in enumerate(design.components.items()):
        fp = _load_footprint(comp.resolved_footprint())
        col, row = idx % cols, idx // cols
        x = margin + col * pitch
        y = margin + row * pitch
        fp.position = Position(X=round(x, 3), Y=round(y, 3))
        _set_text(fp, "reference", ref)
        _set_text(fp, "value", comp.value)
        for pad in fp.pads:
            key = (ref, str(pad.number))
            if key in pad_net:
                code, nname = pad_net[key]
                pad.net = Net(code, nname)
        board.footprints.append(fp)
        xs.append(x); ys.append(y)

    # ---- board outline (Edge.Cuts rectangle) ---------------------------
    if xs:
        pad = pitch
        x0, y0 = min(xs) - pad, min(ys) - pad
        x1, y1 = max(xs) + pad, max(ys) + pad
    else:
        x0, y0, x1, y1 = 0, 0, 40, 30
    outline = GrRect(
        start=Position(X=round(x0, 3), Y=round(y0, 3)),
        end=Position(X=round(x1, 3), Y=round(y1, 3)),
        layer="Edge.Cuts",
        width=0.15,
    )
    board.graphicItems.append(outline)

    path = Path(path)
    board.to_file(str(path))
    return path
