# pcbforge

The core engine of [cursor-for-pcb](https://github.com/agribeacon/cursor-for-pcb).

A high-level circuit `Design` (components + nets) that compiles to real KiCad
artifacts: netlist + ERC (via SKiDL), board file (via kiutils), schematic &
PCB SVGs, DRC, and Gerbers (via `kicad-cli`).

```python
from pcbforge import Design, build_all

d = Design(name="divider")
d.add_component("resistor", "R1", "10k")
d.add_component("resistor", "R2", "10k")
d.connect("VIN", "R1.1")
d.connect("VOUT", "R1.2", "R2.1")
d.connect("GND", "R2.2")
build_all(d, "out/divider")
```

CLI: `pcbforge list`, `pcbforge build <example>`, `pcbforge build-json <file>`.

See the [repo README](../README.md) for the full picture.
