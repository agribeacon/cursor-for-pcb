"""A small but real autorouter: grid-based Lee/maze routing on two copper
layers (F.Cu + B.Cu) with vias.

It is intentionally simple — not a commercial router — but it produces *actual
copper*: tracks and vias that connect the ratsnest, written straight into the
``.kicad_pcb`` and checkable by ``kicad-cli pcb drc``.

Algorithm per net (nets routed shortest-pin-count first):
  * collect pad "access cells" (SMD pads on F.Cu only; through-hole on both);
  * grow a connected tree — BFS (multi-source Lee expansion) from the already
    connected cells to each remaining terminal, avoiding other nets' pads and
    previously-routed copper, with a via cost to change layers;
  * convert each found path into merged straight Segments + Via items.

Power nets (GND/VBUS/3V3/VCC/5V) get wider tracks. Anything it cannot route is
reported back honestly as a failure count (the ratsnest stays for that net).
"""
from __future__ import annotations

import heapq
import hashlib
import math
from dataclasses import dataclass

_uid_seq = 0


def _uuid() -> str:
    """Deterministic unique id (Math.random/uuid4 are unavailable in some
    sandboxes; a counter hashed into uuid shape is stable + unique)."""
    global _uid_seq
    _uid_seq += 1
    h = hashlib.sha1(f"pcbforge-{_uid_seq}".encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"

RES = 0.2             # grid resolution (mm)
CLEAR_CELLS = 2       # obstacle inflation: 2 cells -> 0.4 mm centre spacing
VIA_COST = 14         # discourage layer changes
# 0.2 mm track at 0.4 mm spacing leaves exactly the 0.2 mm edge gap the default
# DRC rule wants. Wider power traces would need per-net clearance rules the fixed
# grid doesn't model, so all tracks share one width to stay DRC-clean.
TRACK_W = 0.2
POWER_TRACK_W = 0.2
VIA_SIZE = 0.6
VIA_DRILL = 0.3
LAYERS = ("F.Cu", "B.Cu")
_POWER_NETS = {"GND", "VBUS", "VCC", "5V", "3V3", "VIN", "VOUT", "+5V", "+3V3"}


@dataclass
class _Pad:
    net: int
    x: float
    y: float
    w: float
    h: float
    both_layers: bool   # through-hole -> can be entered on either layer


# Sentinel owner for copper that belongs to no routable net (e.g. an IC's
# unconnected pads). It is never equal to a real net code, so the router treats
# such cells as hard obstacles and never routes a track across them.
BLOCKER = -1


def _abs_pads(board, include_unconnected=False):
    """Yield (_Pad) for pads. With ``include_unconnected`` also yields pads
    with no net, tagged ``net = BLOCKER`` so they block routing (real copper a
    track must avoid). All coordinates are absolute board mm."""
    pads = []
    for fp in board.footprints:
        ox, oy = fp.position.X, fp.position.Y
        for pad in fp.pads:
            unconnected = pad.net is None or pad.net.number in (None, 0)
            if unconnected and not include_unconnected:
                continue
            netnum = BLOCKER if unconnected else pad.net.number
            px = ox + (pad.position.X or 0)
            py = oy + (pad.position.Y or 0)
            sw = (pad.size.X if pad.size else 0.5)
            sh = (pad.size.Y if pad.size else 0.5)
            both = (pad.type or "").lower() in ("thru_hole", "np_thru_hole")
            pads.append(_Pad(net=netnum, x=px, y=py,
                             w=sw, h=sh, both_layers=both))
    return pads


def route_board(board, skip_net_codes: set[int] | None = None,
                power_net_codes: set[int] | None = None) -> dict:
    """Route the board in place. Returns {nets, routed, failed, tracks, vias}.

    ``skip_net_codes`` are nets the router leaves alone (e.g. a GND net that a
    copper pour will connect instead). ``power_net_codes`` get wider traces."""
    from kiutils.items.brditems import Segment, Via
    from kiutils.items.common import Net, Position

    skip = skip_net_codes or set()
    power = power_net_codes or set()
    pads = _abs_pads(board, include_unconnected=True)
    if not pads:
        return {"nets": 0, "routed": 0, "failed": 0, "tracks": 0, "vias": 0}

    # ---- grid frame ----------------------------------------------------
    margin = 2.0
    minx = min(p.x for p in pads) - margin
    miny = min(p.y for p in pads) - margin
    maxx = max(p.x for p in pads) + margin
    maxy = max(p.y for p in pads) + margin
    W = int((maxx - minx) / RES) + 1
    H = int((maxy - miny) / RES) + 1

    def to_cell(x, y):
        return (int(round((x - minx) / RES)), int(round((y - miny) / RES)))

    def to_mm(c, r):
        return (round(minx + c * RES, 3), round(miny + r * RES, 3))

    # owner[layer][r*W+c] = netcode occupying that cell (pad or routed copper)
    owner = [[0] * (W * H) for _ in LAYERS]

    def stamp(layer_idx, c, r, net, radius=CLEAR_CELLS, only_empty=False):
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                cc, rr = c + dc, r + dr
                if 0 <= cc < W and 0 <= rr < H:
                    idx = rr * W + cc
                    if only_empty and owner[layer_idx][idx] != 0:
                        continue
                    owner[layer_idx][idx] = net

    def stamp_pad(layer_idx, p, net, clearance: bool):
        """Block a pad's copper. ``clearance=False`` stamps only the pad core
        (always wins); ``clearance=True`` adds the surrounding halo but only on
        empty cells, so a halo never erases a neighbouring pad's core."""
        extra = CLEAR_CELLS if clearance else 0
        hc = int(p.w / 2 / RES) + extra
        hr = int(p.h / 2 / RES) + extra
        c0, r0 = to_cell(p.x, p.y)
        for dr in range(-hr, hr + 1):
            for dc in range(-hc, hc + 1):
                cc, rr = c0 + dc, r0 + dr
                if 0 <= cc < W and 0 <= rr < H:
                    idx = rr * W + cc
                    if clearance and owner[layer_idx][idx] != 0:
                        continue
                    owner[layer_idx][idx] = net

    # net -> list of (cell, layers-it-can-enter); pad cell -> exact mm centre
    net_terms: dict[int, list[tuple[tuple[int, int], tuple[int, ...]]]] = {}
    pad_xy: dict[tuple[int, int], tuple[float, float]] = {}
    pad_layers = []
    for p in pads:
        c, r = to_cell(p.x, p.y)
        layers = (0, 1) if p.both_layers else (0,)
        pad_layers.append((p, layers))
        if p.net == BLOCKER:
            continue  # real copper to avoid, but nothing to route to
        net_terms.setdefault(p.net, []).append(((c, r), layers))
        pad_xy[(c, r)] = (round(p.x, 3), round(p.y, 3))
    # phase 1: pad cores (protected); phase 2: clearance halos (fill empty).
    # Only on the layers a pad occupies — a B.Cu track may pass under an SMD pad.
    for p, layers in pad_layers:
        for li in layers:
            stamp_pad(li, p, p.net, clearance=False)
    for p, layers in pad_layers:
        for li in layers:
            stamp_pad(li, p, p.net, clearance=True)

    segments: list = []
    vias: list = []
    routed = failed = 0
    # On small/medium boards plain Lee/Dijkstra (no heuristic) explores fully
    # and finds cleaner geometry; on large boards that's too slow, so switch to
    # the A* heuristic for speed. (Manhattan A* is admissible either way.)
    use_astar = (W * H) > 55000

    # route nets with fewer terminals first (easier, frees space)
    for net in sorted(net_terms, key=lambda n: len(net_terms[n])):
        terms = net_terms[net]
        if len(terms) < 2 or net in skip:
            continue
        ok = _route_net(net, terms, owner, W, H, segments, vias,
                        to_mm, pad_xy, Segment, Via, Net, Position,
                        is_power=net in power, use_astar=use_astar)
        routed += ok
        failed += (len(terms) - 1) - ok

    board.traceItems.extend(segments)
    board.traceItems.extend(vias)
    return {"nets": len(net_terms), "routed": routed, "failed": failed,
            "tracks": len(segments), "vias": len(vias)}


def _route_net(net, terms, owner, W, H, segments, vias, to_mm, pad_xy,
               Segment, Via, Net, Position, is_power=False, use_astar=True) -> int:
    """Connect a net's terminals one by one. Returns #links made."""
    wide = is_power or len(terms) >= 5
    width = POWER_TRACK_W if wide else TRACK_W
    # wider tracks need a wider clearance halo so the extra copper still keeps
    # 0.2 mm to neighbours (a 0.3 mm track at 2-cell spacing would leave 0.1 mm).
    halo = CLEAR_CELLS + (1 if wide else 0)

    def passable(li, c, r):
        o = owner[li][r * W + c]
        return o == 0 or o == net

    # connected = set of (c, r, layer) cells already part of this net
    connected: set[tuple[int, int, int]] = set()
    (c0, r0), ls0 = terms[0]
    for li in ls0:
        connected.add((c0, r0, li))
    pending = terms[1:]
    links = 0

    for (tc, tr), tls in pending:
        targets = {(tc, tr, li) for li in tls}
        path = _lee(connected, targets, owner, W, H, net, passable, use_astar)
        if not path:
            continue
        links += 1
        _emit_path(path, net, width, segments, vias, owner, W, H,
                   to_mm, pad_xy, Segment, Via, Net, Position, halo)
        for cell in path:
            connected.add(cell)
    return links


def _lee(sources, targets, owner, W, H, net, passable, use_astar=True):
    """Shortest-path from any source cell to any target cell. Cells are
    (c, r, layer). With ``use_astar`` a Manhattan heuristic prunes the search
    (fast on big boards); without it, plain Dijkstra explores fully and tends to
    pick cleaner geometry on small boards. Returns the path or None."""
    tcells = {(c, r) for (c, r, _l) in targets}

    def h(c, r):
        if not use_astar:
            return 0
        return min(abs(c - tc) + abs(r - tr) for (tc, tr) in tcells)

    pq = [(h(c, r), 0, (c, r, li)) for (c, r, li) in sources]
    heapq.heapify(pq)
    dist = {s: 0 for s in sources}
    prev: dict = {s: None for s in sources}
    while pq:
        _f, d, cur = heapq.heappop(pq)
        if cur in targets:
            return _reconstruct(prev, cur)
        if d > dist.get(cur, 1 << 30):
            continue
        c, r, li = cur
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            cc, rr = c + dc, r + dr
            if 0 <= cc < W and 0 <= rr < H and passable(li, cc, rr):
                nxt = (cc, rr, li)
                nd = d + 1
                if nd < dist.get(nxt, 1 << 30):
                    dist[nxt] = nd
                    prev[nxt] = cur
                    heapq.heappush(pq, (nd + h(cc, rr), nd, nxt))
        ol = 1 - li
        if passable(ol, c, r):
            nxt = (c, r, ol)
            nd = d + VIA_COST
            if nd < dist.get(nxt, 1 << 30):
                dist[nxt] = nd
                prev[nxt] = cur
                heapq.heappush(pq, (nd + h(c, r), nd, nxt))
    return None


def _reconstruct(prev, cur):
    path = []
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    return path


def _emit_path(path, net, width, segments, vias, owner, W, H,
               to_mm, pad_xy, Segment, Via, Net, Position, halo=CLEAR_CELLS):
    """Turn a cell path into merged Segments + Vias, and mark copper as used.

    Path endpoints that sit on a pad are snapped to the pad's exact centre so
    KiCad registers the track-to-pad connection (grid quantisation otherwise
    leaves a sub-cell gap and the net reads as unconnected)."""
    # mark the centreline plus a clearance halo (without clobbering other
    # nets' copper) so later nets keep their distance.
    for (c, r, li) in path:
        for dr in range(-halo, halo + 1):
            for dc in range(-halo, halo + 1):
                cc, rr = c + dc, r + dr
                if 0 <= cc < W and 0 <= rr < H and owner[li][rr * W + cc] == 0:
                    owner[li][rr * W + cc] = net
        owner[li][r * W + c] = net

    def xy(c, r):
        return pad_xy.get((c, r)) or to_mm(c, r)

    i = 0
    while i < len(path) - 1:
        c, r, li = path[i]
        nc, nr, nli = path[i + 1]
        if nli != li:                       # via at this cell
            x, y = xy(c, r)
            vias.append(Via(position=Position(X=x, Y=y), size=VIA_SIZE,
                            drill=VIA_DRILL, layers=["F.Cu", "B.Cu"],
                            net=net, tstamp=_uuid()))
            i += 1
            continue
        # extend a straight run on this layer
        dc, dr = _sign(nc - c), _sign(nr - r)
        j = i + 1
        while j < len(path):
            pj, pjp = path[j], path[j - 1]
            if (pj[2] != li or _sign(pj[0] - pjp[0]) != dc
                    or _sign(pj[1] - pjp[1]) != dr):
                break
            j += 1
        sx, sy = xy(c, r)
        ex, ey = xy(path[j - 1][0], path[j - 1][1])
        if (sx, sy) != (ex, ey):
            segments.append(Segment(start=Position(X=sx, Y=sy),
                                    end=Position(X=ex, Y=ey), width=width,
                                    layer=LAYERS[li], net=net, tstamp=_uuid()))
        i = j - 1 if j - 1 > i else i + 1


def _sign(v):
    return (v > 0) - (v < 0)


def _is_power(net, terms):
    return len(terms) >= 4   # heuristic; refined by name in route_board caller
