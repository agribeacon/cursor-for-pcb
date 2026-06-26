"""The high-level circuit model the AI / MCP / UI manipulate.

A :class:`Design` is just parts + nets. It is intentionally dumb and fully
serializable (``to_dict`` / ``from_dict``) so it can live in a JSON file, be
streamed over MCP, or be diffed. Compilation to KiCad happens elsewhere
(``build.py``, ``pcb.py``).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import library


@dataclass
class Component:
    ref: str                 # designator, e.g. "R1"
    type: str                # catalog key, e.g. "resistor"
    value: str = ""          # "10k", "100nF", ...
    footprint: str = ""      # override; empty -> catalog default
    props: dict = field(default_factory=dict)

    def resolved_footprint(self) -> str:
        return self.footprint or library.resolve(self.type).footprint


@dataclass
class Connection:
    ref: str
    pin: str                 # friendly pin name or number


@dataclass
class Net:
    name: str
    nodes: list[Connection] = field(default_factory=list)


class DesignError(ValueError):
    pass


_REF_RE = re.compile(r"^[A-Za-z]+\d+$")


@dataclass
class Design:
    name: str = "untitled"
    components: dict[str, Component] = field(default_factory=dict)
    nets: dict[str, Net] = field(default_factory=dict)
    notes: str = ""

    # ---- mutation API (what MCP tools call) -----------------------------
    def add_component(self, type: str, ref: str | None = None,
                      value: str = "", footprint: str = "",
                      **props) -> Component:
        pt = library.resolve(type)            # validates type
        ref = ref or self._auto_ref(pt)
        if not _REF_RE.match(ref):
            raise DesignError(f"Invalid ref '{ref}': use a letter prefix + number, e.g. R1")
        if ref in self.components:
            raise DesignError(f"Component '{ref}' already exists")
        comp = Component(ref=ref, type=pt.key, value=value or pt.default_value,
                         footprint=footprint, props=props)
        self.components[ref] = comp
        return comp

    def remove_component(self, ref: str) -> None:
        self.components.pop(ref, None)
        for net in self.nets.values():
            net.nodes = [n for n in net.nodes if n.ref != ref]

    def connect(self, net: str, *pins: str) -> Net:
        """``connect("VCC", "R1.1", "U1.vin")`` — pins as ``REF.PIN`` strings."""
        n = self.nets.setdefault(net, Net(name=net))
        for spec in pins:
            ref, pin = self._split_pin(spec)
            if ref not in self.components:
                raise DesignError(f"Unknown component '{ref}' in '{spec}'")
            # validate pin resolves
            library.pin_number(library.resolve(self.components[ref].type), pin)
            if not any(c.ref == ref and c.pin == pin for c in n.nodes):
                n.nodes.append(Connection(ref=ref, pin=pin))
        return n

    # ---- helpers --------------------------------------------------------
    def _auto_ref(self, pt: library.PartType) -> str:
        prefix = _PREFIXES.get(pt.key, pt.part[0].upper())
        i = 1
        while f"{prefix}{i}" in self.components:
            i += 1
        return f"{prefix}{i}"

    @staticmethod
    def _split_pin(spec: str) -> tuple[str, str]:
        if "." not in spec:
            raise DesignError(f"Pin spec '{spec}' must be REF.PIN, e.g. R1.2")
        ref, pin = spec.split(".", 1)
        return ref.strip(), pin.strip()

    def validate(self) -> list[str]:
        """Cheap structural lint (not ERC). Returns human-readable warnings."""
        warns: list[str] = []
        if not self.components:
            warns.append("design has no components")
        for ref, comp in self.components.items():
            pins_used = [n.pin for net in self.nets.values()
                         for n in net.nodes if n.ref == ref]
            if not pins_used:
                warns.append(f"{ref} is not connected to any net")
        for name, net in self.nets.items():
            if len(net.nodes) < 2:
                warns.append(f"net '{name}' has fewer than 2 nodes")
        return warns

    # ---- serialization --------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "notes": self.notes,
            "components": [asdict(c) for c in self.components.values()],
            "nets": [
                {"name": net.name, "nodes": [asdict(n) for n in net.nodes]}
                for net in self.nets.values()
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Design":
        design = cls(name=d.get("name", "untitled"), notes=d.get("notes", ""))
        for c in d.get("components", []):
            design.components[c["ref"]] = Component(
                ref=c["ref"], type=c["type"], value=c.get("value", ""),
                footprint=c.get("footprint", ""), props=c.get("props", {}))
        for net in d.get("nets", []):
            design.nets[net["name"]] = Net(
                name=net["name"],
                nodes=[Connection(**n) for n in net.get("nodes", [])])
        return design

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "Design":
        return cls.from_dict(json.loads(Path(path).read_text()))


# Reference designator prefixes by part type.
_PREFIXES = {
    "resistor": "R", "capacitor": "C", "capacitor_polarized": "C",
    "led": "D", "diode": "D", "button": "SW", "header_1x2": "J",
    "header_1x4": "J", "regulator_3v3": "U", "usb_c": "J",
    "inductor": "L", "diode_schottky": "D", "zener": "D",
    "npn": "Q", "nmos": "Q", "mosfet_logic": "Q", "crystal": "Y",
    "fuse": "F", "potentiometer": "RV", "ne555": "U", "opamp": "U",
    "esp32": "U", "reg_5v": "U", "reg_7805": "U", "screw_2": "J",
    "header_1x6": "J", "header_2x4": "J", "usb_micro": "J",
}
