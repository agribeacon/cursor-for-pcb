"""pcbforge — an AI-native PCB design engine.

A high-level circuit :class:`~pcbforge.model.Design` compiles to real KiCad
netlists, boards, schematic SVGs, and fabrication files via SKiDL + kiutils +
kicad-cli.
"""
from __future__ import annotations

from .model import Design, Component, Net, Connection, DesignError
from .project import build_all, BuildResult
from . import (library, build, pcb, render, schematic_svg, pcb_svg, circuits,
               review, bom, blocks, fab, electrical, sim, render_check)

__version__ = "0.1.0"

__all__ = [
    "Design", "Component", "Net", "Connection", "DesignError",
    "build_all", "BuildResult",
    "library", "build", "pcb", "render", "schematic_svg", "circuits",
    "review", "bom",
    "__version__",
]
