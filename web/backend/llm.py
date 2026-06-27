"""LLM-in-the-loop chat: let Claude drive the pcbforge engine via tool use.

When ``ANTHROPIC_API_KEY`` is set, the web chat routes through Claude
(``claude-opus-4-8``) running a manual agentic tool-use loop — it adds parts,
wires nets, and builds the board by calling the same engine the MCP server
exposes. Without a key, the backend falls back to the deterministic parser in
``agent.py`` so the demo still works fully offline.
"""
from __future__ import annotations

import hashlib
import json
import os

from pcbforge import Design, build_all, library, schematic_svg, blocks  # noqa: F401
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
    {
        "name": "list_blocks",
        "description": "List senior-verified circuit blocks you can compose "
                       "(usb_c_power, esp32_core, status_led, i2c_bus, user_button). "
                       "Composing blocks is the preferred way to build — each block "
                       "is already correctly decoupled/strapped.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "add_block",
        "description": "Add a pre-engineered block to the design. 'esp32_core' "
                       "returns the list of free GPIO pins (e.g. 'U1.io4') — use "
                       "those as gpio_pin/scl_pin/sda_pin for the peripheral blocks. "
                       "Add 'usb_c_power' and 'esp32_core' first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "enum": list(blocks.BLOCKS)},
                "gpio_pin": {"type": "string"},
                "scl_pin": {"type": "string"},
                "sda_pin": {"type": "string"},
                "color": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "review_design",
        "description": "Run a senior design review (decoupling, bulk caps, LED "
                       "resistors, USB-C CC pulldowns, MCU straps, ERC/DRC). "
                       "Returns a graded report — fix any errors it lists.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

SYSTEM = """You are a senior hardware engineer working inside cursor-for-pcb, an
AI-native PCB tool focused on ESP32-class boards. Turn the user's request into a
complete, manufacturable circuit, then `build` and `review_design`, fixing any
errors before finishing.

PREFER BLOCKS. The fastest way to a correct board is to compose senior-verified
blocks with `add_block` (see `list_blocks`): start with `usb_c_power`, then
`esp32_core` (it returns the free GPIO pins), then peripheral blocks
(`status_led`, `i2c_bus`, `user_button`) wired to those GPIOs. Blocks come
pre-decoupled and pre-strapped, so a block-composed board passes review by
construction. Drop to raw add_part/connect only for parts no block covers.

Pin syntax: 'REF.PIN'. Passives use numbers (R1.1, R1.2, C1.+, C1.-). ICs and
connectors use friendly names (U1.vin, U1.vout, U1.gnd, U1.3v3, U1.en, U1.io0,
J1.vbus, J1.gnd, J1.cc1, J1.cc2, D1.a, D1.k).

Senior design rules — apply them every time, the review enforces them:
- One common GND net. Tie every ground pin to it.
- DECOUPLING: every IC/regulator/MCU power pin gets a 100nF cap to GND right at
  the pin, plus a bulk cap (≥10uF) on each power rail.
- LED: always a series current-limiting resistor (≈330R–1k).
- Match the input to the request: for a plain "5V" or "3.3V" input use a 2-pin
  header (header_1x2), NOT a USB-C connector. Only add USB-C when the user asks
  for USB / USB-C — and then use the `usb_c_power` block so CC is wired right.
- USB-C as a power sink: 5.1k pulldown from EACH of CC1 and CC2 to GND. NEVER
  tie CC1/CC2 directly to GND — that's a wiring error (reads as an e-marked
  cable, not a sink). Each CC needs its own net through a 5.1k resistor to GND.
- Linear regulator (AMS1117): input bulk cap (10uF) on Vin, output bulk (≥10uF)
  + 100nF on Vout.
- ESP32: 3V3 + 100nF + 10uF decoupling; EN needs a 10k pull-up to 3V3 and a
  100nF to GND (reset RC); IO0 needs a 10k pull-up to 3V3 (boot strap). Add a
  reset button (EN–GND) and boot button (IO0–GND) when making a dev board.
- Never leave a power input, reset, or enable pin floating.

If unsure which parts/pins exist, call list_part_types. Keep replies short; let
the rendered board, the review grade, and the BOM do the talking."""


# ---- tool dispatch (pure; unit-testable without the LLM) --------------------
def execute_tool(state: dict, name: str, args: dict) -> tuple[str, bool]:
    """Run one tool against the design held in ``state['design']``.

    Returns (result_text, did_build). May replace ``state['design']``.
    """
    d: Design = state["design"]
    did_build = False

    def cached_build():
        """Build once per unique design — `build` then `review_design` on the
        same design reuses the result instead of routing twice."""
        h = hashlib.sha1(json.dumps(d.to_dict(), sort_keys=True).encode()).hexdigest()
        if state.get("build_hash") == h and state.get("build"):
            return state["build"]
        res = build_all(d, state["out_dir"](d), fast=True)
        state["build"] = res.to_dict()
        state["build_hash"] = h
        return state["build"]

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
            b = cached_build()
            rv = b.get("review") or {}
            return (f"build ok={b['ok']} ERC_errors={b['erc_errors']} "
                    f"DRC_unconnected={b['drc_unconnected']} copper_DRC={b['drc_copper']} "
                    f"tracks={b['tracks']} | review grade={rv.get('grade')} "
                    f"({rv.get('errors')} errors)"), True
        if name == "list_blocks":
            return json.dumps(blocks.BLOCK_HELP), False
        if name == "add_block":
            fn = blocks.BLOCKS.get(args["name"])
            if not fn:
                return f"unknown block {args['name']}", False
            opts = {k: v for k, v in args.items()
                    if k != "name" and v not in (None, "")}
            info = fn(d, **opts)
            return json.dumps(info), False
        if name == "review_design":
            b = cached_build()
            rv = b.get("review") or {}
            issues = [f["message"] for f in rv.get("findings", [])
                      if f["severity"] in ("error", "warn")]
            return json.dumps({"grade": rv.get("grade"), "score": rv.get("score"),
                               "max_score": rv.get("max_score"),
                               "issues": issues}), True
        return f"unknown tool {name}", False
    except Exception as exc:
        return f"ERROR: {exc}", did_build


def run(state: dict, message: str, history: list, on_event=None) -> tuple[str, bool]:
    """Drive Claude through a tool-use loop. Returns (reply, did_build).

    Each call is self-contained: rather than replaying a (fragile, easily
    desynced) tool-use transcript, we show Claude the *current* design state so
    follow-ups still work, and start a fresh message thread.

    ``on_event(dict)`` (optional) is called as work happens — Claude's interim
    text ({"type":"text",...}) and each tool call ({"type":"tool",...}) — so a
    UI can show the live thinking / tool activity.
    """
    import anthropic

    def emit(ev):
        if on_event:
            on_event(ev)

    d: Design = state["design"]
    system = SYSTEM
    if d.components:
        system += ("\n\nCURRENT DESIGN (modify this, don't start over unless "
                   f"asked):\n{json.dumps(d.to_dict())}")

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": message}]
    did_build = False
    reply = ""

    for _ in range(14):  # cap tool-use rounds
        resp = client.messages.create(
            model=MODEL, max_tokens=4096, system=system,
            tools=TOOLS, messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})
        # surface Claude's interim reasoning/narration
        for block in resp.content:
            if block.type == "text" and block.text.strip():
                emit({"type": "text", "text": block.text.strip()})
        if resp.stop_reason != "tool_use":
            reply = "".join(b.text for b in resp.content if b.type == "text")
            break
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                arg = block.input or {}
                label = arg.get("name") or arg.get("type") or arg.get("net") or ""
                emit({"type": "tool", "name": block.name,
                      "arg": str(label)[:40]})
                out, built = execute_tool(state, block.name, block.input)
                did_build = did_build or built
                emit({"type": "tool_result", "name": block.name,
                      "summary": out.splitlines()[0][:90] if out else ""})
                results.append({"type": "tool_result",
                                "tool_use_id": block.id, "content": out})
        messages.append({"role": "user", "content": results})

    return (reply or "Done — see the board and review.", did_build)
