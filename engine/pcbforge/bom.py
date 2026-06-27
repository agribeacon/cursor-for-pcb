"""Bill of materials — the deliverable a senior hands to procurement/fab.

Groups identical parts (same type + value + footprint) into one line with the
combined reference designators and quantity, ordered by designator prefix.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict

from . import library
from .model import Design


def _natural_ref(ref: str) -> tuple[str, int]:
    i = len(ref)
    while i > 0 and ref[i - 1].isdigit():
        i -= 1
    return (ref[:i], int(ref[i:] or 0))


def bom_rows(design: Design) -> list[dict]:
    groups: dict[tuple, list[str]] = defaultdict(list)
    meta: dict[tuple, dict] = {}
    for ref, comp in design.components.items():
        pt = library.resolve(comp.type)
        key = (comp.type, comp.value, comp.resolved_footprint())
        groups[key].append(ref)
        meta[key] = {"description": pt.description}
    rows = []
    for key, refs in groups.items():
        ctype, value, footprint = key
        refs_sorted = sorted(refs, key=_natural_ref)
        rows.append({
            "References": ", ".join(refs_sorted),
            "Qty": len(refs_sorted),
            "Value": value,
            "Type": ctype,
            "Footprint": footprint,
            "Description": meta[key]["description"],
        })
    rows.sort(key=lambda r: _natural_ref(r["References"].split(",")[0]))
    return rows


def bom_csv(design: Design) -> str:
    rows = bom_rows(design)
    buf = io.StringIO()
    cols = ["References", "Qty", "Value", "Type", "Footprint", "Description"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()
