"""Starlette backend for the pcbforge web UI.

Wraps the engine behind a tiny JSON API and serves the single-page frontend.
Holds one current design in memory (chat-session style), mirroring the MCP
server. SVGs are returned inline so the frontend can drop them straight into
the DOM.

Run:  pcbforge-web   (or: uvicorn web.backend.app:app --reload)
"""
from __future__ import annotations

import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, FileResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from pcbforge import Design, build_all, library, schematic_svg, blocks
from pcbforge.circuits import EXAMPLES

from . import agent, llm

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
WORKSPACE = Path(os.environ.get("PCBFORGE_WORKSPACE",
                                Path.home() / ".pcbforge" / "web"))
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---- session state ------------------------------------------------------
_state = {"design": Design(name="untitled"), "build": None, "history": []}


def _out_dir(d: Design) -> Path:
    p = WORKSPACE / d.name
    p.mkdir(parents=True, exist_ok=True)
    return p


def _snapshot(build_result=None) -> dict:
    d: Design = _state["design"]
    pcb = None
    if build_result and build_result.get("pcb_svg"):
        p = Path(build_result["pcb_svg"])
        if p.exists():
            pcb = p.read_text()
    return {
        "design": d.to_dict(),
        "warnings": d.validate(),
        "schematic_svg": schematic_svg.render(d) if d.components else "",
        "pcb_svg": pcb,
        "build": build_result,
    }


def _do_build() -> dict:
    d: Design = _state["design"]
    res = build_all(d, _out_dir(d))
    _state["build"] = res.to_dict()
    return _state["build"]


# ---- routes -------------------------------------------------------------
async def state(request):
    return JSONResponse(_snapshot(_state["build"]))


async def parts(request):
    return JSONResponse({
        "parts": library.list_types(),
        "blocks": [{"name": n, "help": blocks.BLOCK_HELP.get(n, "")}
                   for n in blocks.BLOCKS],
        "examples": list(EXAMPLES),
    })


async def add(request):
    """Manually add a part or a block to the current design (palette click)."""
    body = await request.json()
    kind = body.get("kind", "part")
    name = body.get("name", "")
    try:
        if kind == "block":
            fn = blocks.BLOCKS.get(name)
            if not fn:
                return JSONResponse({"error": f"unknown block {name}"}, status_code=400)
            fn(_state["design"])
            msg = f"added block {name}"
        else:
            comp = _state["design"].add_component(name, value=body.get("value", ""))
            msg = f"added {comp.ref}"
        _state["build"] = None
        return JSONResponse({"message": msg, "state": _snapshot(None)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def chat(request):
    body = await request.json()
    message = body.get("message", "")
    if llm.available():
        # Claude drives the engine via tool use; it calls `build` itself.
        # Run in a threadpool so the blocking LLM + build don't freeze the server.
        _state["out_dir"] = _out_dir
        reply, did_build = await run_in_threadpool(
            llm.run, _state, message, _state.get("history", []))
        build_result = _state["build"] if did_build else None
        return JSONResponse({"reply": reply, "did_build": did_build,
                             "state": _snapshot(build_result), "engine": "llm"})
    design, reply, should_build = agent.handle(_state["design"], message)
    _state["design"] = design
    _state["build"] = None
    build_result = await run_in_threadpool(_do_build) if should_build else None
    return JSONResponse({"reply": reply, "did_build": should_build,
                         "state": _snapshot(build_result), "engine": "parser"})


async def build(request):
    result = await run_in_threadpool(_do_build)
    return JSONResponse({"state": _snapshot(result)})


async def new_design(request):
    _state["design"] = Design(name="untitled")
    _state["build"] = None
    _state["history"] = []
    return JSONResponse({"state": _snapshot(None)})


async def pcb_file(request):
    """Serve the current design's real .kicad_pcb so KiCanvas can render it
    in-browser with native KiCad look + zoom/pan."""
    d = _state["design"]
    path = _out_dir(d) / f"{d.name}.kicad_pcb"
    if not path.exists():
        return JSONResponse({"error": "no board yet"}, status_code=404)
    return FileResponse(path, media_type="application/octet-stream",
                        headers={"Cache-Control": "no-store"})


async def index(request):
    return FileResponse(FRONTEND / "index.html")


routes = [
    Route("/", index),
    Route("/api/state", state),
    Route("/api/parts", parts),
    Route("/api/chat", chat, methods=["POST"]),
    Route("/api/build", build, methods=["POST"]),
    Route("/api/new", new_design, methods=["POST"]),
    Route("/api/add", add, methods=["POST"]),
    Route("/api/pcb_file", pcb_file),
]

app = Starlette(routes=routes)
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1",
                port=int(os.environ.get("PCBFORGE_PORT", "8765")))


if __name__ == "__main__":
    main()
