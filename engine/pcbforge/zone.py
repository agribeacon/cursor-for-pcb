"""Copper pour (zone) support.

KiCad's zone *filling* algorithm lives in ``pcbnew`` (the GUI engine), which
isn't importable from a plain venv — but it *is* present in KiCad's bundled
Python. So we author nothing here; we shell out to that interpreter with
``_kicad_zone_fill.py`` to add filled GND pours and save the board in place.

A ground pour means the router doesn't have to route GND at all: every GND pad
ties straight into the surrounding copper, which is exactly how real boards are
built and which clears most of the congestion on dense parts.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import kicad_env


def fill_zones(board_path: str | Path, nets: list[str],
               layers: tuple[str, ...] = ("F.Cu", "B.Cu")) -> bool:
    """Add + fill a pour for each net on each layer. Returns True on success.

    Needs KiCad's bundled Python (for ``pcbnew``); if it can't be found we skip
    pouring and leave the routed board untouched.
    """
    py = kicad_env.find_pcbnew_python()
    if not py or not nets:
        return False
    script = str(Path(__file__).resolve().parent / "_kicad_zone_fill.py")
    ok = False
    for layer in layers:
        res = subprocess.run([py, script, str(board_path), ",".join(nets), layer],
                             capture_output=True, text=True)
        if "zones_made=" in (res.stdout or ""):
            ok = True
    return ok
