"""Locate the installed KiCad symbol/footprint libraries and the ``kicad-cli``
binary, then export the environment variables SKiDL and kiutils expect.

This is the single place that knows *where* KiCad lives, so the rest of the
engine never hard-codes a path. Import this module (or call :func:`setup`)
before touching SKiDL.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

# Candidate roots that contain ``symbols/`` and ``footprints/`` dirs.
_LIB_ROOTS = [
    # macOS .app bundle
    Path.home() / "Applications/KiCad/KiCad.app/Contents/SharedSupport",
    Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport"),
    # Linux
    Path("/usr/share/kicad"),
    Path("/usr/local/share/kicad"),
    # Windows
    Path("C:/Program Files/KiCad/9.0/share/kicad"),
    Path("C:/Program Files/KiCad/8.0/share/kicad"),
]

# Symbol-dir env vars across KiCad major versions; SKiDL probes all of them.
_SYMBOL_VARS = [
    "KICAD_SYMBOL_DIR",
    "KICAD6_SYMBOL_DIR",
    "KICAD7_SYMBOL_DIR",
    "KICAD8_SYMBOL_DIR",
    "KICAD9_SYMBOL_DIR",
]
_FOOTPRINT_VARS = [
    "KICAD6_FOOTPRINT_DIR",
    "KICAD7_FOOTPRINT_DIR",
    "KICAD8_FOOTPRINT_DIR",
    "KICAD9_FOOTPRINT_DIR",
]


class KicadNotFound(RuntimeError):
    pass


def find_lib_root() -> Path:
    """Return the SharedSupport/share root that holds symbol + footprint libs."""
    env = os.environ.get("KICAD_SHARE_DIR")
    if env and (Path(env) / "symbols").is_dir():
        return Path(env)
    for root in _LIB_ROOTS:
        if (root / "symbols").is_dir() and (root / "footprints").is_dir():
            return root
    raise KicadNotFound(
        "Could not locate KiCad shared libraries. Install KiCad, or set "
        "KICAD_SHARE_DIR to the dir containing 'symbols/' and 'footprints/'."
    )


def find_cli() -> str:
    """Return an absolute path to the ``kicad-cli`` executable."""
    cli = shutil.which("kicad-cli")
    if cli:
        return cli
    candidates = [
        Path.home() / "Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
        Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    raise KicadNotFound("kicad-cli not found on PATH or in the KiCad app bundle.")


def find_pcbnew_python() -> str | None:
    """Path to KiCad's bundled Python (the one that can ``import pcbnew``).

    Used for zone filling, which needs the GUI engine. Returns None if not
    found, so callers can degrade gracefully.
    """
    env = os.environ.get("KICAD_PYTHON")
    if env and Path(env).exists():
        return env
    candidates = list(
        (Path.home() / "Applications/KiCad/KiCad.app/Contents/Frameworks/"
         "Python.framework/Versions").glob("*/bin/python3*"))
    candidates += list(
        Path("/Applications/KiCad/KiCad.app/Contents/Frameworks/"
             "Python.framework/Versions").glob("*/bin/python3*"))
    for c in candidates:
        if c.exists():
            return str(c)
    return None


_DONE = False


def setup() -> dict[str, Path]:
    """Idempotently export KiCad env vars. Returns useful resolved paths."""
    global _DONE
    root = find_lib_root()
    symbols = root / "symbols"
    footprints = root / "footprints"
    for var in _SYMBOL_VARS:
        os.environ.setdefault(var, str(symbols))
    for var in _FOOTPRINT_VARS:
        os.environ.setdefault(var, str(footprints))
    _DONE = True
    return {"root": root, "symbols": symbols, "footprints": footprints,
            "cli": Path(find_cli())}


def symbol_dir() -> Path:
    return find_lib_root() / "symbols"


def footprint_dir() -> Path:
    return find_lib_root() / "footprints"


def footprint_path(lib_id: str) -> Path:
    """``Resistor_SMD:R_0805_2012Metric`` -> absolute .kicad_mod path."""
    lib, name = lib_id.split(":", 1)
    return footprint_dir() / f"{lib}.pretty" / f"{name}.kicad_mod"


# Auto-setup on import so callers can just ``import pcbforge``.
try:  # pragma: no cover - best effort
    setup()
except KicadNotFound:
    pass
