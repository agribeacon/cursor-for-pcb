"""End-to-end tests: every example circuit must produce a clean netlist
(0 ERC errors) and a real board file that renders to SVG."""
import os
from pathlib import Path

import pytest

from pcbforge import Design, build_all
from pcbforge.circuits import EXAMPLES, build_example
from pcbforge import library


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_example_builds(name, tmp_path):
    design = build_example(name)
    res = build_all(design, tmp_path / name, drc=True)
    # netlist + schematic always exist
    assert Path(res.netlist).exists(), res.errors
    assert Path(res.schematic_svg).exists()
    assert os.path.getsize(res.schematic_svg) > 0
    # no ERC errors and no hard build errors
    assert res.erc_errors == 0, res.errors
    assert not res.errors, res.errors
    # a real board + rendered SVG
    assert res.pcb_file and Path(res.pcb_file).exists()
    assert res.pcb_svg and Path(res.pcb_svg).exists()
    # autorouter laid copper and fully connected the ratsnest
    assert res.tracks > 0, "no tracks routed"
    assert res.unrouted == 0, "router left ratsnest"
    assert res.drc_unconnected == 0, "DRC reports unconnected pads"


def test_clean_board_passes_copper_drc(tmp_path):
    """A board with no fine-pitch parts must autoroute with zero copper
    (short/clearance) DRC violations."""
    import json
    design = build_example("power_led_board")
    res = build_all(design, tmp_path / "p", drc=True)
    drc = json.loads(Path(res.pcb_file).with_suffix(".drc.json").read_text())
    copper = [v for v in drc.get("violations", [])
              if v.get("type") in ("shorting_items", "clearance", "track_dangling")]
    assert not copper, f"copper DRC violations: {copper}"


def test_design_roundtrip(tmp_path):
    d = build_example("voltage_divider")
    f = tmp_path / "d.json"
    d.save(f)
    d2 = Design.load(f)
    assert d2.to_dict() == d.to_dict()


def test_friendly_pins_resolve():
    pt = library.resolve("regulator_3v3")
    assert library.pin_number(pt, "vin") == "3"
    assert library.pin_number(pt, "vout") == "2"
    assert library.pin_number(pt, "gnd") == "1"


def test_unknown_part_raises():
    d = Design()
    with pytest.raises(Exception):
        d.add_component("flux_capacitor", "U1")
