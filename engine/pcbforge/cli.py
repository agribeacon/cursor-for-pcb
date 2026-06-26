"""Command-line entry point: ``pcbforge``.

    pcbforge list                       # list part types and example circuits
    pcbforge build <example> [-o DIR]   # build a built-in example
    pcbforge build-json <file.json>     # build a design from JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import library
from .circuits import EXAMPLES, build_example
from .model import Design
from .project import build_all


def _print_result(res) -> int:
    print(f"\n=== {res.name} ===")
    print(f"out:        {res.out_dir}")
    print(f"netlist:    {res.netlist}")
    print(f"schematic:  {res.schematic_svg}")
    print(f"board:      {res.pcb_file}")
    print(f"pcb svg:    {res.pcb_svg}")
    print(f"ERC:        {res.erc_errors} errors, {res.erc_warnings} warnings")
    print(f"DRC:        {res.drc_violations} violations, "
          f"{res.drc_unconnected} unconnected")
    for w in res.warnings:
        print(f"  warn: {w}")
    for e in res.errors:
        print(f"  ERROR: {e}")
    print("OK" if res.ok else "FAILED")
    return 0 if res.ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pcbforge")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list part types and example circuits")

    b = sub.add_parser("build", help="build a built-in example")
    b.add_argument("example", choices=list(EXAMPLES))
    b.add_argument("-o", "--out", default=None)
    b.add_argument("--gerbers", action="store_true")

    bj = sub.add_parser("build-json", help="build a design from a JSON file")
    bj.add_argument("file")
    bj.add_argument("-o", "--out", default=None)
    bj.add_argument("--gerbers", action="store_true")

    args = p.parse_args(argv)

    if args.cmd == "list":
        print("PART TYPES:")
        for t in library.list_types():
            print(f"  {t['type']:20} {t['symbol']:35} pins={t['pins']}")
        print("\nEXAMPLE CIRCUITS:")
        for name in EXAMPLES:
            print(f"  {name}")
        return 0

    if args.cmd == "build":
        design = build_example(args.example)
        out = args.out or f"out/{design.name}"
        return _print_result(build_all(design, out, gerbers=args.gerbers))

    if args.cmd == "build-json":
        design = Design.from_dict(json.loads(Path(args.file).read_text()))
        out = args.out or f"out/{design.name}"
        return _print_result(build_all(design, out, gerbers=args.gerbers))

    return 1


if __name__ == "__main__":
    sys.exit(main())
