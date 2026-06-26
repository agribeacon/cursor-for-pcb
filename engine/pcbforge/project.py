"""Orchestrate a full build of a :class:`~pcbforge.model.Design` into a
directory of artifacts: design JSON, netlist, ERC report, board file,
schematic SVG, PCB SVG, DRC report.

This is the function the MCP server and the web backend call.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import build, pcb, render, schematic_svg
from .model import Design


@dataclass
class BuildResult:
    name: str
    out_dir: str
    design_json: str
    netlist: str
    schematic_svg: str
    pcb_file: str | None = None
    pcb_svg: str | None = None
    erc_errors: int = 0
    erc_warnings: int = 0
    drc_violations: int = 0
    drc_unconnected: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and self.erc_errors == 0

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["ok"] = self.ok
        return d


def build_all(design: Design, out_dir: str | Path,
              gerbers: bool = False, drc: bool = True) -> BuildResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    res = BuildResult(
        name=design.name, out_dir=str(out),
        design_json=str(out / "design.json"),
        netlist=str(out / f"{design.name}.net"),
        schematic_svg=str(out / "schematic.svg"),
    )
    res.warnings.extend(design.validate())

    design.save(res.design_json)

    # schematic SVG never fails — write it first so the UI always has a view.
    Path(res.schematic_svg).write_text(schematic_svg.render(design))

    # netlist + ERC
    try:
        build.generate_netlist(design, res.netlist)
        erc = build.run_erc(design)
        res.erc_errors, res.erc_warnings = erc.errors, erc.warnings
    except Exception as exc:
        res.errors.append(f"netlist/ERC failed: {exc}")

    # board + PCB SVG + DRC
    try:
        pcb_file = out / f"{design.name}.kicad_pcb"
        pcb.build_board(design, pcb_file)
        res.pcb_file = str(pcb_file)
        res.pcb_svg = str(out / "pcb.svg")
        render.pcb_to_svg(pcb_file, res.pcb_svg)
        if drc:
            d = render.run_drc(pcb_file)
            res.drc_violations, res.drc_unconnected = d.violations, d.unconnected
        if gerbers:
            render.export_gerbers(pcb_file, out / "gerbers")
    except Exception as exc:
        res.errors.append(f"PCB build failed: {exc}")

    return res
