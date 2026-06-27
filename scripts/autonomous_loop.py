"""Autonomous MCP-driven self-improvement loop.

Connects to the pcbforge MCP server as a client, builds a deliberately flawed
ESP32 power board, asks the server to *review* it, then auto-fixes every finding
the review reports and re-reviews — demonstrating create → review → improve all
through the MCP interface, with no human in the loop.
"""
import asyncio
import json
import os
import re
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

VENV_BIN = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "pcbforge-mcp"


def text(res):
    return res.content[0].text if res.content else ""


async def call(s, tool, **args):
    return text(await s.call_tool(tool, args))


async def add_part(s, type, value=""):
    out = await call(s, "add_part", type=type, value=value)
    m = re.match(r"added ([A-Za-z]+\d+)", out)
    return m.group(1)


async def review(s):
    return json.loads(await call(s, "review_design"))


async def main():
    env = dict(os.environ)
    env["PCBFORGE_WORKSPACE"] = os.path.expanduser("~/.pcbforge/auto")
    params = StdioServerParameters(command=str(VENV_BIN), env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print("✓ connected to pcbforge MCP\n")

            # ---- 1. create a DELIBERATELY FLAWED board --------------------
            # Standard-pitch 5V→3.3V supply with a status LED, but missing all
            # decoupling — a senior would reject it.
            await call(s, "new_design", name="auto_psu")
            j1 = await add_part(s, "header_1x2")        # 5V in
            u1 = await add_part(s, "regulator_3v3", value="AMS1117-3.3")
            r1 = await add_part(s, "resistor", "330")
            d1 = await add_part(s, "led", "GRN")
            j2 = await add_part(s, "header_1x2")        # 3V3 out
            await call(s, "connect", net="VIN", pins=[f"{j1}.1", f"{u1}.vin"])
            await call(s, "connect", net="GND",
                       pins=[f"{j1}.2", f"{u1}.gnd", f"{d1}.k", f"{j2}.2"])
            await call(s, "connect", net="3V3",
                       pins=[f"{u1}.vout", f"{r1}.1", f"{j2}.1"])
            await call(s, "connect", net="LED", pins=[f"{r1}.2", f"{d1}.a"])
            print("① built a flawed 5V→3.3V board (no decoupling at all)")

            before = await review(s)
            print(f"   REVIEW: grade {before['grade']} "
                  f"({before['score']}/{before['max_score']}), "
                  f"{before['errors']} errors")

            # ---- 2. ITERATE: review → fix → re-review until grade A -------
            graded = before
            for it in range(1, 4):
                issues = [f for f in graded["findings"]
                          if f["severity"] in ("error", "warn")]
                if graded["grade"] == "A" or not issues:
                    break
                print(f"\n② iteration {it}: fixing {len(issues)} findings…")
                for f in issues:
                    code = f["code"]
                    if code.startswith("DECAP"):
                        c = await add_part(s, "capacitor", "100nF")
                        await call(s, "connect", net="3V3", pins=[f"{c}.1"])
                        await call(s, "connect", net="GND", pins=[f"{c}.2"])
                        print(f"     ✓ added {c} (100nF decoupling)")
                    elif code.startswith("BULK:"):
                        rail = code.split(":", 1)[1]
                        c = await add_part(s, "capacitor_polarized", "10uF")
                        await call(s, "connect", net=rail, pins=[f"{c}.+"])
                        await call(s, "connect", net="GND", pins=[f"{c}.-"])
                        print(f"     ✓ added {c} (10uF bulk on {rail})")
                graded = await review(s)
                print(f"   RE-REVIEW: grade {graded['grade']} "
                      f"({graded['score']}/{graded['max_score']}), "
                      f"{graded['errors']} errors")

            print(f"\n=== SELF-IMPROVEMENT: {before['grade']} "
                  f"({before['errors']} err) → {graded['grade']} "
                  f"({graded['errors']} err) ===")

            # ---- 3. export a complete fab package -------------------------
            pkg = json.loads(await call(s, "export_fab"))
            print(f"\n③ FAB PACKAGE → {pkg['zip'].split('/')[-1]}")
            print(f"   {pkg['n_gerbers']} gerbers + drill + Pick&Place + BOM + notes")
            print(f"   pick & place: {pkg['pick_and_place'].split('/')[-1]}")
            print(f"   BOM:          {pkg['bom'].split('/')[-1]}")


if __name__ == "__main__":
    asyncio.run(main())
