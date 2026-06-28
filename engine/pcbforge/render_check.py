"""Render-fidelity rules — prove the SVG reflects the data and nothing else.

A view can't be trusted just because it's drawn from data: the drawing code can
still drop an element, invent one, or overlap two so the board is unreadable.
These are deterministic checks (software-lint style) over the *rendered* SVG:

  * FIDELITY: every component (data-ref) and net (data-net) in the design appears
    in the SVG, and the SVG contains no ref/net that isn't in the design — so the
    picture can neither omit nor fabricate connectivity.
  * OVERLAP: no two component symbols overlap (unreadable layout).

Run as a normal check; the tests assert these hold for every example.
"""
from __future__ import annotations

import re

from .model import Design

_REF = re.compile(r'data-ref="([^"]+)"')
_NET = re.compile(r'data-net="([^"]+)"')
_GROUP = re.compile(r'<g class="comp" data-ref="([^"]+)">(.*?)</g>', re.S)
_NUM = re.compile(r'[-\d.]+')


def fidelity(design: Design, svg: str) -> list[str]:
    """Return a list of fidelity violations (empty == the SVG matches the data)."""
    issues = []
    svg_refs = set(_REF.findall(svg))
    svg_nets = set(_NET.findall(svg))
    data_refs = set(design.components)
    data_nets = set(design.nets)

    missing_refs = data_refs - svg_refs
    extra_refs = svg_refs - data_refs
    if missing_refs:
        issues.append(f"SVG is missing components: {sorted(missing_refs)}")
    if extra_refs:
        issues.append(f"SVG invented components not in the design: {sorted(extra_refs)}")

    # only multi-pin nets get drawn (a 1-pin net has nothing to connect); so the
    # SVG nets must be a subset of data nets, and must include every net that
    # actually connects >= 2 pins.
    drawn_worthy = {n for n, net in design.nets.items() if len(net.nodes) >= 2}
    if extra := (svg_nets - data_nets):
        issues.append(f"SVG invented nets not in the design: {sorted(extra)}")
    if missing := (drawn_worthy - svg_nets):
        issues.append(f"SVG dropped connected nets: {sorted(missing)}")
    return issues


def _bbox(group_body: str):
    """Rough bbox of a component group from its numeric coordinates."""
    xs, ys = [], []
    for m in re.finditer(r'[xc]x?="([-\d.]+)"\s+[yc]?y="([-\d.]+)"', group_body):
        xs.append(float(m.group(1))); ys.append(float(m.group(2)))
    # also catch x=/y= and cx=/cy=
    for m in re.finditer(r'\b(?:x|cx)="([-\d.]+)"', group_body):
        xs.append(float(m.group(1)))
    for m in re.finditer(r'\b(?:y|cy)="([-\d.]+)"', group_body):
        ys.append(float(m.group(1)))
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def overlaps(svg: str) -> list[str]:
    """Return pairs of component symbols whose bounding boxes overlap."""
    boxes = {}
    for ref, body in _GROUP.findall(svg):
        bb = _bbox(body)
        if bb:
            boxes[ref] = bb
    issues = []
    refs = list(boxes)
    for i in range(len(refs)):
        for j in range(i + 1, len(refs)):
            ax0, ay0, ax1, ay1 = boxes[refs[i]]
            bx0, by0, bx1, by1 = boxes[refs[j]]
            # shrink a touch so adjacent (touching) boxes aren't flagged
            if ax0 < bx1 - 2 and bx0 < ax1 - 2 and ay0 < by1 - 2 and by0 < ay1 - 2:
                issues.append(f"{refs[i]} overlaps {refs[j]}")
    return issues


def check(design: Design, svg: str) -> list[str]:
    return fidelity(design, svg) + overlaps(svg)
