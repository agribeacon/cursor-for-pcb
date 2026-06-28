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


@pytest.mark.parametrize("name", ["power_led_board", "usb_3v3", "esp32_dev_board"])
def test_designs_are_electrically_senior(name, tmp_path):
    """The real designs must pass the senior design review with ZERO electrical
    errors — every IC decoupled, power rails bulked, LEDs current-limited, USB-C
    CC pulldowns present, MCU straps pulled. (Copper-routing warnings on dense
    boards are a separate, non-electrical concern.)"""
    design = build_example(name)
    res = build_all(design, tmp_path / name, drc=True)
    assert res.erc_errors == 0
    assert res.drc_unconnected == 0, "ratsnest must be fully connected"
    assert res.review["errors"] == 0, res.review["findings"]
    assert res.review["grade"] in ("A", "B"), res.review


def test_blocks_compose_to_senior_grade(tmp_path):
    """A board composed purely from senior-verified blocks must pass the review
    with zero electrical errors and an A/B grade."""
    design = build_example("esp32_iot_node")
    res = build_all(design, tmp_path / "iot", drc=True)
    assert res.erc_errors == 0
    assert res.review["errors"] == 0, res.review["findings"]
    assert res.review["grade"] in ("A", "B"), res.review


def test_power_led_board_grade_A(tmp_path):
    """A complete standard-pitch board must earn grade A (0 errors, 0 warnings)."""
    res = build_all(build_example("power_led_board"), tmp_path / "p", drc=True)
    assert res.review["grade"] == "A", res.review["findings"]


def test_fab_package_is_complete(tmp_path):
    """The fab package must contain everything a board house needs."""
    import zipfile
    from pcbforge import fab
    design = build_example("power_led_board")
    res = build_all(design, tmp_path / "f", drc=False)
    pkg = fab.export_fab(res.pcb_file, design, tmp_path / "f")
    names = zipfile.ZipFile(pkg["zip"]).namelist()
    assert any(n.endswith("-pos.csv") for n in names), "missing Pick & Place"
    assert any(n.endswith("-bom.csv") for n in names), "missing BOM"
    assert any("Edge_Cuts" in n for n in names), "missing board outline"
    assert any("Paste" in n for n in names), "missing paste/stencil"
    assert any(n.endswith(".drl") for n in names), "missing drill"
    assert any(n.endswith("F_Cu.gtl") for n in names), "missing copper gerber"


def test_simulation_catches_unsafe_led(tmp_path):
    """SPICE must catch a resistor that overdrives the LED (33Ω on 5V ≈ 82 mA)."""
    from pcbforge import sim
    if not sim.has_ngspice():
        import pytest as _pt
        _pt.skip("ngspice not installed")
    d = Design(name="bad")
    d.add_component("header_1x2", "J1")
    d.add_component("resistor", "R1", "33")
    d.add_component("led", "D1", "RED")
    d.connect("5V", "J1.1", "R1.1")
    d.connect("LED", "R1.2", "D1.a")
    d.connect("GND", "J1.2", "D1.k")
    res = build_all(d, tmp_path / "b", drc=True)
    assert res.review["errors"] >= 1
    assert any("burn" in f["message"] for f in res.review["findings"])


def test_simulation_verifies_regulator_rail(tmp_path):
    """SPICE must read back ~3.3 V on the regulated rail of a good board."""
    from pcbforge import sim
    if not sim.has_ngspice():
        import pytest as _pt
        _pt.skip("ngspice not installed")
    res = build_all(build_example("power_led_board"), tmp_path / "p", drc=False)
    assert res.simulation["ok"]
    assert abs(res.simulation["voltages"].get("3V3", 0) - 3.3) < 0.1


@pytest.mark.parametrize("name", ["led_resistor", "power_led_board", "usb_3v3",
                                  "esp32_dev_board", "esp32_iot_node"])
def test_schematic_render_is_faithful(name):
    """The schematic SVG must reflect the design exactly — no invented or dropped
    components/nets, and no overlapping symbols (the view can't lie)."""
    from pcbforge import schematic_svg, render_check
    d = build_example(name)
    issues = render_check.check(d, schematic_svg.render(d))
    assert not issues, issues


def test_render_check_catches_fabrication():
    """The fidelity rule must catch a net that isn't in the design."""
    from pcbforge import schematic_svg, render_check
    d = build_example("led_resistor")
    bad = schematic_svg.render(d).replace(
        "</svg>", '<g class="net" data-net="GHOST"></g></svg>')
    assert any("GHOST" in m for m in render_check.fidelity(d, bad))


def test_bom_groups_parts():
    from pcbforge import bom
    design = build_example("power_led_board")
    csv = bom.bom_csv(design)
    assert "References,Qty,Value" in csv
    assert "capacitor_polarized" in csv


def test_simple_board_copper_clean(tmp_path):
    """Standard-pitch boards must autoroute with zero copper DRC violations."""
    import json
    for name in ("led_resistor", "voltage_divider"):
        design = build_example(name)
        res = build_all(design, tmp_path / name, drc=True)
        drc = json.loads(Path(res.pcb_file).with_suffix(".drc.json").read_text())
        copper = [v for v in drc.get("violations", [])
                  if v.get("type") in ("shorting_items", "clearance", "track_dangling")]
        assert not copper, f"{name} copper DRC violations: {copper}"


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
