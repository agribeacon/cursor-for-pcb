"""LLM-in-the-loop chat: let Claude drive the pcbforge engine via tool use.

When ``ANTHROPIC_API_KEY`` is set, the web chat routes through Claude
(``claude-opus-4-8``) running a manual agentic tool-use loop — it adds parts,
wires nets, and builds the board by calling the same engine the MCP server
exposes. Without a key, the backend falls back to the deterministic parser in
``agent.py`` so the demo still works fully offline.
"""
from __future__ import annotations

import json
import os

from pcbforge import Design, build_all, library, schematic_svg  # noqa: F401
from pcbforge.circuits import EXAMPLES, build_example

MODEL = os.environ.get("PCBFORGE_LLM_MODEL", "claude-opus-4-8")


def available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except Exception:
        return False


# ---- tools Claude can call --------------------------------------------------
TOOLS = [
    {
        "name": "list_part_types",
        "description": "List every part type in the catalog with its friendly "
                       "pin names. Call this if unsure what parts/pins exist.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "new_design",
        "description": "Start a fresh empty design with the given name.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "load_example",
        "description": f"Load a built-in example as the design. One of: {list(EXAMPLES)}.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "enum": list(EXAMPLES)}},
            "required": ["name"],
        },
    },
    {
        "name": "add_part",
        "description": "Add a component. type is a catalog key (e.g. 'resistor', "
                       "'led', 'regulator_3v3', 'usb_c', 'esp32'). ref auto-generates "
                       "(R1, U1...) if omitted.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "ref": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["type"],
        },
    },
    {
        "name": "connect",
        "description": "Connect pins onto a net. pins are 'REF.PIN' where PIN is a "
                       "number or friendly name (e.g. 'U1.vin', 'R1.2', 'D1.a', "
                       "'J1.gnd'). Reusing a net name extends it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "net": {"type": "string"},
                "pins": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["net", "pins"],
        },
    },
    {
        "name": "remove_part",
        "description": "Remove a component and detach it from all nets.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string"}},
            "required": ["ref"],
        },
    },
    {
        "name": "get_design",
        "description": "Return the current design (components + nets) and lint warnings.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "build",
        "description": "Compile the design into a real KiCad netlist + autorouted "
                       "board, run ERC + DRC, and render the schematic and PCB. Call "
                       "this when the design is complete to 'make it real'.",
        "input_schema": {
            "type": "object",
            "properties": {"gerbers": {"type": "boolean"}},
        },
    },
]

SYSTEM = """You are the design copilot inside cursor-for-pcb, an AI-native PCB tool.
You turn a user's request into a real circuit by calling tools: add components,
wire nets, then build. Work in small steps and finish by calling `build` so the
user sees the schematic, PCB and DRC result.

Rules:
- Pins are 'REF.PIN'. Passives use numbers (R1.1, R1.2, C1.+, C1.-). ICs/connectors
  use friendly names (U1.vin, U1.vout, U1.gnd, J1.vbus, J1.gnd, D1.a, D1.k).
- For a USB-C power input, add 'usb_c' and a 'regulator_3v3', decouple with caps,
  and remember USB-C CC1/CC2 need 5.1k pulldowns to GND for a sink device.
- Always tie a common GND net. Add a current-limiting resistor in series with any LED.
- If unsure which parts/pins exist, call list_part_types first.
- Keep replies short; let the tools and the rendered board do the talking."""


# ---- tool dispatch (pure; unit-testable without the LLM) --------------------
def execute_tool(state: dict, name: str, args: dict) -> tuple[str, bool]:
    """Run one tool against the design held in ``state['design']``.

    Returns (result_text, did_build). May replace ``state['design']``.
    """
    d: Design = state["design"]
    did_build = False
    try:
        if name == "list_part_types":
            return json.dumps([t["type"] for t in library.list_types()]), False
        if name == "new_design":
            state["design"] = Design(name=args["name"])
            return f"new design '{args['name']}'", False
        if name == "load_example":
            state["design"] = build_example(args["name"])
            return f"loaded example '{args['name']}'", False
        if name == "add_part":
            c = d.add_component(args["type"], ref=args.get("ref") or None,
                                value=args.get("value", ""))
            return f"added {c.ref} ({c.type} {c.value})".rstrip(), False
        if name == "connect":
            d.connect(args["net"], *args["pins"])
            return f"net {args['net']} now connects {', '.join(args['pins'])}", False
        if name == "remove_part":
            d.remove_component(args["ref"])
            return f"removed {args['ref']}", False
        if name == "get_design":
            return json.dumps(d.to_dict()), False
        if name == "build":
            res = build_all(d, state["out_dir"](d), gerbers=args.get("gerbers", False))
            state["build"] = res.to_dict()
            did_build = True
            return (f"build ok={res.ok} ERC_errors={res.erc_errors} "
                    f"DRC_violations={res.drc_violations} "
                    f"unconnected={res.drc_unconnected} tracks={res.tracks}"), True
        return f"unknown tool {name}", False
    except Exception as exc:
        return f"ERROR: {exc}", did_build


def run(state: dict, message: str, history: list) -> tuple[str, bool]:
    """Drive Claude through a tool-use loop. Returns (reply, did_build)."""
    import anthropic

    client = anthropic.Anthropic()
    messages = list(history) + [{"role": "user", "content": message}]
    did_build = False
    reply = ""

    for _ in range(12):  # cap tool-use rounds
        resp = client.messages.create(
            model=MODEL, max_tokens=4096, system=SYSTEM,
            tools=TOOLS, messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            reply = "".join(b.text for b in resp.content if b.type == "text")
            break
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                out, built = execute_tool(state, block.name, block.input)
                did_build = did_build or built
                results.append({"type": "tool_result",
                                "tool_use_id": block.id, "content": out})
        messages.append({"role": "user", "content": results})

    # keep transcript bounded for the next turn
    state["history"] = messages[-12:]
    return (reply or "Done.", did_build)
