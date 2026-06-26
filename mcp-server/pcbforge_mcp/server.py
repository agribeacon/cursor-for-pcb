"""pcbforge MCP server.

Exposes the PCB-design engine as MCP tools so an AI agent (Claude Code) can
drive board design end-to-end: spin up a design, drop in parts, wire nets,
build it into a real KiCad netlist + board, and read back the rendered
schematic / PCB SVGs and the ERC/DRC verdicts.

State model: one *current design* per server process (a simple, chat-friendly
session). ``new_design`` / ``load_example`` reset it. Everything is persisted
under a workspace dir so artifacts survive and the web UI can read them.

Run:  pcbforge-mcp           (stdio transport, for Claude Code)
"""
from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from pcbforge import Design, build_all, library
from pcbforge.circuits import EXAMPLES, build_example

WORKSPACE = Path(os.environ.get("PCBFORGE_WORKSPACE",
                                Path.home() / ".pcbforge" / "workspace"))
WORKSPACE.mkdir(parents=True, exist_ok=True)

mcp = FastMCP("pcbforge")

# ---- session state ------------------------------------------------------
_design: Design = Design(name="untitled")


def _summary(d: Design) -> str:
    lines = [f"Design: {d.name}", f"  components ({len(d.components)}):"]
    for ref, c in d.components.items():
        lines.append(f"    {ref}: {c.type} {c.value}".rstrip())
    lines.append(f"  nets ({len(d.nets)}):")
    for name, net in d.nets.items():
        pins = ", ".join(f"{n.ref}.{n.pin}" for n in net.nodes)
        lines.append(f"    {name}: {pins}")
    return "\n".join(lines)


def _out_dir(d: Design) -> Path:
    p = WORKSPACE / d.name
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---- discovery tools ----------------------------------------------------
@mcp.tool()
def list_part_types() -> list[dict]:
    """List every part type the catalog knows, with symbol, footprint, and
    the friendly pin names you can use in `connect`."""
    return library.list_types()


@mcp.tool()
def list_examples() -> list[str]:
    """List built-in reference circuits you can load with `load_example`."""
    return list(EXAMPLES)


# ---- design mutation ----------------------------------------------------
@mcp.tool()
def new_design(name: str) -> str:
    """Start a fresh, empty design. Resets the current session."""
    global _design
    _design = Design(name=name)
    return _summary(_design)


@mcp.tool()
def load_example(name: str) -> str:
    """Load a built-in example circuit as the current design."""
    global _design
    _design = build_example(name)
    return _summary(_design)


@mcp.tool()
def add_part(type: str, ref: str = "", value: str = "",
             footprint: str = "") -> str:
    """Add a component. `type` is a catalog key (e.g. 'resistor', 'led',
    'regulator_3v3', 'usb_c'). `ref` auto-generates (R1, C1, U1...) if omitted.
    Returns the updated design summary."""
    comp = _design.add_component(type, ref=ref or None, value=value,
                                 footprint=footprint)
    return f"added {comp.ref} ({comp.type} {comp.value})\n\n" + _summary(_design)


@mcp.tool()
def remove_part(ref: str) -> str:
    """Remove a component and detach it from all nets."""
    _design.remove_component(ref)
    return _summary(_design)


@mcp.tool()
def connect(net: str, pins: list[str]) -> str:
    """Connect pins onto a net. Each pin is 'REF.PIN', where PIN is a number
    or a friendly name (e.g. 'U1.vin', 'R1.2', 'D1.a'). Reusing a net name
    adds to it. Example: connect('GND', ['U1.gnd', 'C1.-', 'J1.gnd'])."""
    _design.connect(net, *pins)
    return _summary(_design)


@mcp.tool()
def get_design() -> dict:
    """Return the current design as structured JSON plus a text summary and
    structural lint warnings."""
    return {
        "design": _design.to_dict(),
        "summary": _summary(_design),
        "warnings": _design.validate(),
    }


# ---- compile / verify / export -----------------------------------------
@mcp.tool()
def build(gerbers: bool = False) -> dict:
    """Compile the current design into a real KiCad netlist + board, render the
    schematic and PCB SVGs, and run ERC + DRC. Returns artifact paths and the
    verdicts. This is the main 'make it real' action."""
    res = build_all(_design, _out_dir(_design), gerbers=gerbers)
    return res.to_dict()


@mcp.tool()
def get_schematic_svg() -> str:
    """Return the schematic SVG markup for the current design (rebuilds it)."""
    from pcbforge import schematic_svg
    return schematic_svg.render(_design)


@mcp.tool()
def get_pcb_svg() -> str:
    """Return the PCB SVG markup. Builds the board first if needed."""
    out = _out_dir(_design)
    svg = out / "pcb.svg"
    if not svg.exists():
        build_all(_design, out)
    return svg.read_text() if svg.exists() else "<svg/>"


@mcp.tool()
def export_gerbers() -> str:
    """Generate Gerber + drill fabrication files and return the directory."""
    res = build_all(_design, _out_dir(_design), gerbers=True)
    if res.errors:
        return "build failed: " + "; ".join(res.errors)
    return str(_out_dir(_design) / "gerbers")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
