"""Run *inside KiCad's bundled Python* (has ``pcbnew``) to add and fill copper
pour zones. Invoked as a subprocess by :mod:`pcbforge.zone`.

    <kicad-python> _kicad_zone_fill.py <board.kicad_pcb> <NET1,NET2,...> <layer>

Adds one filled zone per named net on the given layer (default B.Cu), covering
the board outline, then fills all zones and saves the board in place.
"""
import sys

import pcbnew


def main():
    board_path = sys.argv[1]
    net_names = [n for n in sys.argv[2].split(",") if n]
    layer_name = sys.argv[3] if len(sys.argv) > 3 else "B.Cu"
    layer = {"B.Cu": pcbnew.B_Cu, "F.Cu": pcbnew.F_Cu}[layer_name]

    board = pcbnew.LoadBoard(board_path)
    bbox = board.GetBoardEdgesBoundingBox()
    inset = pcbnew.FromMM(0.4)
    x0, y0 = bbox.GetLeft() + inset, bbox.GetTop() + inset
    x1, y1 = bbox.GetRight() - inset, bbox.GetBottom() - inset

    made = 0
    for name in net_names:
        net = board.FindNet(name)
        if net is None:
            continue
        zone = pcbnew.ZONE(board)
        zone.SetLayer(layer)
        zone.SetNetCode(net.GetNetCode())
        zone.SetIsFilled(True)
        zone.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        poly = zone.Outline()
        poly.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            poly.Append(int(x), int(y))
        board.Add(zone)
        made += 1

    if made:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(board_path, board)
    print(f"zones_made={made}")


if __name__ == "__main__":
    main()
