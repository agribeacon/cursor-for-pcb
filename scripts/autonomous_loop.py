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

            # ---- 1. create a DELIBERATELY FLAWED board (power only) --------
            await call(s, "new_design", name="auto_esp32")
            j1 = await add_part(s, "usb_c")
            u2 = await add_part(s, "regulator_3v3", value="AMS1117-3.3")
            u1 = await add_part(s, "esp32")
            await call(s, "connect", net="VBUS", pins=[f"{j1}.vbus", f"{u2}.vin"])
            await call(s, "connect", net="GND",
                       pins=[f"{j1}.gnd", f"{u2}.gnd", f"{u1}.gnd"])
            await call(s, "connect", net="3V3", pins=[f"{u2}.vout", f"{u1}.3v3"])
            print("① built a flawed ESP32 power board (no decoupling/straps/CC)")

            before = await review(s)
            print(f"   REVIEW: grade {before['grade']} "
                  f"({before['score']}/{before['max_score']}), "
                  f"{before['errors']} errors")
            issues = [f["message"] for f in before["findings"]
                      if f["severity"] in ("error", "warn")]
            for i in issues:
                print(f"     ✗ {i}")

            # ---- 2. AUTO-FIX each finding ---------------------------------
            print("\n② auto-fixing findings…")
            fixed = []
            for f in before["findings"]:
                code = f["code"]
                if code.startswith("DECAP"):
                    c = await add_part(s, "capacitor", "100nF")
                    await call(s, "connect", net="3V3", pins=[f"{c}.1"])
                    await call(s, "connect", net="GND", pins=[f"{c}.2"])
                    fixed.append(f"added {c} (100nF decoupling) for {code}")
                elif code == "BULK:VBUS":
                    c = await add_part(s, "capacitor_polarized", "10uF")
                    await call(s, "connect", net="VBUS", pins=[f"{c}.+"])
                    await call(s, "connect", net="GND", pins=[f"{c}.-"])
                    fixed.append(f"added {c} (10uF bulk on VBUS)")
                elif code == "BULK:3V3":
                    c = await add_part(s, "capacitor_polarized", "22uF")
                    await call(s, "connect", net="3V3", pins=[f"{c}.+"])
                    await call(s, "connect", net="GND", pins=[f"{c}.-"])
                    fixed.append(f"added {c} (22uF bulk on 3V3)")
                elif code in ("STRAP:U1.en", "STRAP:U1.reset") or code.endswith(".en"):
                    rr = await add_part(s, "resistor", "10k")
                    await call(s, "connect", net="EN", pins=[f"{u1}.en", f"{rr}.2"])
                    await call(s, "connect", net="3V3", pins=[f"{rr}.1"])
                    fixed.append(f"added {rr} (10k EN pull-up)")
                elif code.endswith(".io0"):
                    rr = await add_part(s, "resistor", "10k")
                    await call(s, "connect", net="IO0", pins=[f"{u1}.io0", f"{rr}.2"])
                    await call(s, "connect", net="3V3", pins=[f"{rr}.1"])
                    fixed.append(f"added {rr} (10k IO0 boot strap)")
                elif code.startswith("CC:"):
                    cc = code.split(".")[-1]            # cc1 / cc2
                    rr = await add_part(s, "resistor", "5.1k")
                    await call(s, "connect", net=cc.upper(),
                               pins=[f"{j1}.{cc}", f"{rr}.1"])
                    await call(s, "connect", net="GND", pins=[f"{rr}.2"])
                    fixed.append(f"added {rr} (5.1k {cc.upper()} pulldown)")
            for x in fixed:
                print(f"     ✓ {x}")

            # ---- 3. RE-REVIEW ---------------------------------------------
            after = await review(s)
            print(f"\n③ RE-REVIEW: grade {after['grade']} "
                  f"({after['score']}/{after['max_score']}), "
                  f"{after['errors']} errors")
            print(f"\n=== SELF-IMPROVEMENT: {before['grade']} "
                  f"({before['errors']} err) → {after['grade']} "
                  f"({after['errors']} err) ===")
            bom = await call(s, "export_bom")
            print(f"\nfinal BOM ({len(bom.splitlines())-1} lines):")
            print(bom)


if __name__ == "__main__":
    asyncio.run(main())
