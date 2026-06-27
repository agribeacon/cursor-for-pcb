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
def list_blocks() -> dict:
    """List senior-verified circuit blocks you can compose with `add_block`
    (usb_c_power, esp32_core, status_led, i2c_bus, user_button). Composing
    blocks yields a board that passes the design review by construction."""
    from pcbforge import blocks
    return blocks.BLOCK_HELP


@mcp.tool()
def add_block(name: str, gpio_pin: str = "", scl_pin: str = "",
              sda_pin: str = "", color: str = "", value: str = "") -> str:
    """Add a pre-engineered block. Add 'usb_c_power' then 'esp32_core' first;
    `esp32_core` returns the free GPIO pins to wire peripheral blocks to."""
    from pcbforge import blocks
    fn = blocks.BLOCKS.get(name)
    if not fn:
        return f"unknown block '{name}'. Have: {list(blocks.BLOCKS)}"
    opts = {k: v for k, v in dict(gpio_pin=gpio_pin, scl_pin=scl_pin,
            sda_pin=sda_pin, color=color, value=value).items() if v}
    info = fn(_design, **opts)
    return f"added block {name}\n{info}\n\n" + _summary(_design)


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
def review_design() -> dict:
    """Run a senior-engineer design review of the current design: checks IC
    decoupling, power-rail bulk caps, LED series resistors, USB-C CC pulldowns,
    MCU strap pull-ups, unconnected parts, plus (after a build) ERC, unconnected
    ratsnest, copper DRC and ground pour. Returns a graded report."""
    from pcbforge import review as _review
    build = build_all(_design, _out_dir(_design)).to_dict()
    return _review.review(_design, build).to_dict()


@mcp.tool()
def simulate() -> dict:
    """Run a SPICE (ngspice) simulation of the current design and read back the
    operating point — node voltages and LED/branch currents — to verify the
    circuit actually works (e.g. the 3.3V rail measures 3.3V, LED current is in
    a safe range, no rail-to-GND short). The deepest validation layer."""
    from pcbforge import sim as _sim
    res = _sim.run(_design)
    return {"ok": res.get("ok", False), "reason": res.get("reason"),
            "voltages": {k: round(v, 3) for k, v in
                         (res.get("voltages") or {}).items() if v is not None},
            "findings": [f.__dict__ for f in res.get("findings", [])]}


@mcp.tool()
def export_bom() -> str:
    """Return the bill of materials as CSV (parts grouped with quantities)."""
    from pcbforge import bom as _bom
    return _bom.bom_csv(_design)


@mcp.tool()
def export_fab() -> dict:
    """Build the board and produce a complete fabrication package a PCB house can
    run directly: Gerbers (incl. paste/stencil + Edge.Cuts outline), Excellon
    drill, Pick & Place centroid CSV, BOM CSV, and fab-notes — zipped. Returns
    the zip path and the file manifest."""
    from pcbforge import fab as _fab
    out = _out_dir(_design)
    res = build_all(_design, out, gerbers=False)
    if not res.pcb_file:
        return {"error": "build failed: " + "; ".join(res.errors)}
    return _fab.export_fab(res.pcb_file, _design, out)


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
