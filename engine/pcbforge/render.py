"""Thin wrappers around ``kicad-cli`` for rendering and verification.

Everything here shells out to the real KiCad CLI, so the artifacts are exactly
what an engineer would get from the GUI: an SVG of the board, a DRC report,
and Gerber/drill fabrication files.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import kicad_env


def _run(args: list[str]) -> subprocess.CompletedProcess:
    cli = kicad_env.find_cli()
    return subprocess.run([cli, *args], capture_output=True, text=True)


def pcb_to_svg(pcb: str | Path, out: str | Path,
               layers: str = "F.Cu,B.Cu,F.SilkS,Edge.Cuts") -> Path:
    out = Path(out)
    res = _run(["pcb", "export", "svg", "--output", str(out),
                "--layers", layers, "--page-size-mode", "2", str(pcb)])
    if not out.exists():
        raise RuntimeError(f"pcb->svg failed: {res.stderr or res.stdout}")
    return out


def pcb_to_png(pcb: str | Path, out: str | Path) -> Path | None:
    out = Path(out)
    res = _run(["pcb", "render", "--output", str(out), str(pcb)])
    return out if out.exists() else None


@dataclass
class DrcReport:
    violations: int
    unconnected: int
    text: str
    raw: dict

    @property
    def ok(self) -> bool:
        return self.violations == 0


def run_drc(pcb: str | Path) -> DrcReport:
    out = Path(str(pcb)).with_suffix(".drc.json")
    res = _run(["pcb", "drc", "--format", "json", "--output", str(out),
                "--exit-code-violations", str(pcb)])
    raw: dict = {}
    if out.exists():
        try:
            raw = json.loads(out.read_text())
        except Exception:
            raw = {}
    violations = len(raw.get("violations", []))
    unconnected = len(raw.get("unconnected_items", []))
    text = (res.stdout + res.stderr).strip()
    return DrcReport(violations=violations, unconnected=unconnected,
                     text=text, raw=raw)


def export_gerbers(pcb: str | Path, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _run(["pcb", "export", "gerbers", "--output", str(out_dir), str(pcb)])
    _run(["pcb", "export", "drill", "--output", str(out_dir), str(pcb)])
    return out_dir
