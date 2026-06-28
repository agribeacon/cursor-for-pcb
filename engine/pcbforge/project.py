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
    bom: str | None = None
    erc_errors: int = 0
    erc_warnings: int = 0
    drc_violations: int = 0
    drc_unconnected: int = 0
    drc_copper: int = 0
    review: dict = field(default_factory=dict)
    simulation: dict = field(default_factory=dict)
    tracks: int = 0
    vias: int = 0
    routed: int = 0
    unrouted: int = 0
    poured: list = field(default_factory=list)
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
              gerbers: bool = False, drc: bool = True,
              fast: bool = False) -> BuildResult:
    """Build a design into artifacts + review. ``fast`` does a single placement
    candidate (for snappy interactive use); the default tries several and keeps
    the cleanest by DRC."""
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

    # bill of materials (a senior deliverable)
    try:
        from . import bom as _bom
        res.bom = str(out / "bom.csv")
        Path(res.bom).write_text(_bom.bom_csv(design))
    except Exception as exc:
        res.warnings.append(f"BOM failed: {exc}")

    # netlist + ERC
    try:
        build.generate_netlist(design, res.netlist)
        erc = build.run_erc(design)
        res.erc_errors, res.erc_warnings = erc.errors, erc.warnings
    except Exception as exc:
        res.errors.append(f"netlist/ERC failed: {exc}")

    # board + PCB SVG + DRC. Try both placement strategies and keep whichever
    # routes cleaner (fewest copper violations, then fewest unrouted links).
    try:
        pcb_file = out / f"{design.name}.kicad_pcb"
        # Candidate strategies, adaptive to keep small boards fast. Order
        # matters: ties are broken by *first*, so the GND-pour candidate is
        # listed first (real boards want a ground plane).
        gnd_pads = max((len(n.nodes) for name, n in design.nets.items()
                        if name.upper() in pcb.POUR_NETS), default=0)
        n_parts = len(design.components)
        candidates = []
        if fast:
            # one candidate only — pour if there's a ground to plane, else plain
            candidates.append(("pour", "insertion", True) if gnd_pads >= 3
                              else ("ins", "insertion", False))
        else:
            if drc and gnd_pads >= 3:
                candidates.append(("pour", "insertion", True))   # ground plane
            candidates.append(("ins", "insertion", False))        # baseline
            # connectivity candidate is an extra route+DRC pass — only worth it
            # on small/medium boards where routing is fast.
            if drc and 6 < n_parts <= 12:
                candidates.append(("con", "connectivity", False))
        best = None  # (score_tuple, rstats, drc_report, tmp_path)
        for label, order, pour in candidates:
            tmp = out / f".cand_{label}.kicad_pcb"
            info = pcb.build_board(design, tmp, order=order, pour=pour)
            rs = info.get("route", {}) or {}
            rep = render.run_drc(tmp) if drc else None
            copper = _copper_violations(rep) if rep else 0
            unconn = rep.unconnected if rep else 0
            # Compare on electrical quality only (shorts/clearance/unconnected,
            # then unrouted links, then via count). Cosmetic silk warnings are
            # ignored, and since the pour candidate is listed first it wins ties
            # — giving a ground plane whenever it's electrically just as clean.
            score = (copper + unconn, rs.get("failed", 0), rs.get("vias", 0))
            if best is None or score < best[0]:
                best = (score, rs, rep, tmp)
            if not drc:
                break  # no DRC to compare on; first candidate wins
        _, rstats, rep, tmp = best
        win_drc = Path(tmp).with_suffix(".drc.json")
        Path(tmp).replace(pcb_file)
        if win_drc.exists():
            win_drc.replace(pcb_file.with_suffix(".drc.json"))
        # drop the other candidates' leftovers
        for label, _o, _p in candidates:
            (out / f".cand_{label}.kicad_pcb").unlink(missing_ok=True)
            (out / f".cand_{label}.drc.json").unlink(missing_ok=True)
        res.tracks = rstats.get("tracks", 0)
        res.vias = rstats.get("vias", 0)
        res.routed = rstats.get("routed", 0)
        res.unrouted = rstats.get("failed", 0)
        res.poured = rstats.get("poured", [])
        res.pcb_file = str(pcb_file)
        res.pcb_svg = str(out / "pcb.svg")
        # preview = copper + board outline only, so the routing reads clearly.
        # Silkscreen (refs/outlines) is busy and overlaps SMD pads by footprint
        # default; it's still in the fab gerbers, just not this preview.
        render.pcb_to_svg(pcb_file, res.pcb_svg, layers="F.Cu,B.Cu,Edge.Cuts")
        if rep:
            res.drc_violations, res.drc_unconnected = rep.violations, rep.unconnected
            res.drc_copper = _copper_violations(rep)
        if gerbers:
            render.export_gerbers(pcb_file, out / "gerbers")
    except Exception as exc:
        res.errors.append(f"PCB build failed: {exc}")

    # SPICE simulation (run the circuit) — feeds the review
    sim_result = None
    try:
        from . import sim as _sim
        sim_result = _sim.run(design)
        res.simulation = {
            "ok": sim_result.get("ok", False),
            "reason": sim_result.get("reason"),
            "voltages": {k: round(v, 3) for k, v in
                         (sim_result.get("voltages") or {}).items() if v is not None},
            "findings": [f.__dict__ for f in sim_result.get("findings", [])],
        }
    except Exception as exc:
        res.warnings.append(f"simulation failed: {exc}")

    # senior design review over the design + build verdicts + simulation
    try:
        from . import review as _review
        rv = _review.review(design, res.to_dict(), sim_result)
        res.review = rv.to_dict()
    except Exception as exc:
        res.warnings.append(f"review failed: {exc}")

    return res


def _copper_violations(rep) -> int:
    """Count only electrically-meaningful DRC violations (shorts/clearance),
    ignoring cosmetic silkscreen warnings."""
    if not rep or not rep.raw:
        return 0
    bad = ("shorting_items", "clearance", "track_dangling", "copper_edge_clearance")
    return sum(1 for v in rep.raw.get("violations", []) if v.get("type") in bad)
