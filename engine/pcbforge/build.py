"""Compile a :class:`~pcbforge.model.Design` into SKiDL, then emit a KiCad
netlist and run electrical-rules-check (ERC).

SKiDL keeps circuit state in a process-global, so every build starts with
``reset()``. We translate our friendly pin names to KiCad pin numbers via the
catalog before handing them to SKiDL.
"""
from __future__ import annotations

import contextlib
import io
import re
from dataclasses import dataclass
from pathlib import Path

from . import kicad_env  # noqa: F401  (side effect: sets env vars)
from . import library
from .model import Design


@dataclass
class ErcReport:
    errors: int
    warnings: int
    text: str

    @property
    def ok(self) -> bool:
        return self.errors == 0


def _build_skidl(design: Design):
    import skidl
    from skidl import Part, Net, reset, set_default_tool, KICAD8

    reset()
    set_default_tool(KICAD8)

    parts: dict[str, Part] = {}
    for ref, comp in design.components.items():
        pt = library.resolve(comp.type)
        parts[ref] = Part(pt.lib, pt.part, value=comp.value or pt.default_value,
                          footprint=comp.resolved_footprint(), ref=ref)

    for net_name, net in design.nets.items():
        n = Net(net_name)
        for node in net.nodes:
            pt = library.resolve(design.components[node.ref].type)
            pin_no = library.pin_number(pt, node.pin)
            n += parts[node.ref][pin_no]

    return skidl, parts


def generate_netlist(design: Design, path: str | Path) -> Path:
    """Build the circuit and write a KiCad ``.net`` file."""
    skidl, _ = _build_skidl(design)
    path = Path(path)
    skidl.generate_netlist(file_=str(path))
    return path


def run_erc(design: Design) -> ErcReport:
    """Run SKiDL ERC and return a structured report (counts + captured text)."""
    skidl, _ = _build_skidl(design)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            skidl.ERC()
        except Exception as exc:  # pragma: no cover - defensive
            buf.write(f"\nERC raised: {exc!r}")
    text = buf.getvalue()
    errors = _count(text, "ERC errors") + _count(text, "errors found")
    warnings = _count(text, "ERC warnings") + _count(text, "warnings found")
    # SKiDL also stashes counts on its logger.
    try:
        errors = max(errors, skidl.erc_logger.error.count)  # type: ignore[attr-defined]
        warnings = max(warnings, skidl.erc_logger.warning.count)  # type: ignore[attr-defined]
    except Exception:
        pass
    return ErcReport(errors=errors, warnings=warnings, text=text.strip())


_NUM_RE = re.compile(r"(\d+)\s+%s")


def _count(text: str, label: str) -> int:
    m = re.search(rf"(\d+)\s+{re.escape(label)}", text)
    return int(m.group(1)) if m else 0
