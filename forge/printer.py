"""Bambu Studio preset resolution.

Lesson learned the hard way: the Bambu Studio CLI does NOT resolve the `inherits`
chain of a preset passed with --load-settings. A system preset loaded as-is
silently slices with a 200x200x100 bed, PLA, and 0 g of filament. So every preset
is flattened here (system presets, then user presets on top), and the slicer
module checks the resulting G-code header against what was asked for.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import config
from .config import ForgeError

KINDS = ("machine", "process", "filament")


@lru_cache
def _index() -> dict[tuple[str, str], tuple[Path, dict]]:
    idx: dict[tuple[str, str], tuple[Path, dict]] = {}
    roots = [config.BAMBU_SYSTEM]
    if config.BAMBU_USER.exists():
        roots += sorted(p for p in config.BAMBU_USER.iterdir() if p.is_dir())
    for root in roots:  # later roots (user) override earlier (system)
        for kind in KINDS:
            for p in (root / kind).rglob("*.json") if (root / kind).exists() else []:
                try:
                    d = json.loads(p.read_text())
                except Exception:
                    continue
                if isinstance(d, dict) and "name" in d:
                    idx[(kind, d["name"])] = (p, d)
    if not idx:
        raise ForgeError(f"No Bambu presets found under {config.BAMBU_SYSTEM}. Open Bambu Studio once.")
    return idx


def flatten(kind: str, name: str, _depth: int = 0) -> dict:
    if _depth > 20:
        raise ForgeError(f"inherits loop at {kind}/{name}")
    try:
        _, d = _index()[(kind, name)]
    except KeyError:
        near = [n for (k, n) in _index() if k == kind and name.split("@")[0].strip().lower() in n.lower()][:8]
        raise ForgeError(f"No {kind} preset named {name!r}. Close matches: {near}")
    parent = flatten(kind, d["inherits"], _depth + 1) if d.get("inherits") else {}
    out = {**parent, **d}
    out.pop("inherits", None)
    # The CLI rejects 'from: User' presets with flattened parents in compatibility checks,
    # and rejects a missing 'from'. 'system' passes both.
    out["from"] = "system"
    return out


def _f(v):
    if isinstance(v, list):
        v = v[0]
    return float(str(v).rstrip("%"))


@dataclass
class Printer:
    machine: dict
    process: dict
    filament: dict
    bed_type: str = "Textured PEI Plate"
    overrides: dict = field(default_factory=dict)

    @property
    def bed_xy(self) -> tuple[float, float]:
        pts = [tuple(map(float, s.split("x"))) for s in self.machine["printable_area"]]
        xs, ys = zip(*pts)
        return max(xs) - min(xs), max(ys) - min(ys)

    @property
    def bed_z(self) -> float:
        return _f(self.machine["printable_height"])

    @property
    def exclude_xy(self) -> tuple[float, float]:
        pts = [tuple(map(float, s.split("x"))) for s in self.machine.get("bed_exclude_area", ["0x0"])]
        xs, ys = zip(*pts)
        return max(xs) - min(xs), max(ys) - min(ys)

    @property
    def nozzle(self) -> float:
        return _f(self.machine["nozzle_diameter"])

    @property
    def layer(self) -> float:
        return _f(self.process["layer_height"])

    @property
    def line_width(self) -> float:
        return _f(self.process.get("outer_wall_line_width") or self.process["line_width"])

    @property
    def support_angle(self) -> float:
        return _f(self.process.get("support_threshold_angle", 30)) or 30.0

    @property
    def density(self) -> float:
        return _f(self.filament["filament_density"])

    @property
    def cost_per_kg(self) -> float:
        return _f(self.filament.get("filament_cost", 0))

    def write(self, outdir: Path, support: bool) -> tuple[Path, Path, Path]:
        outdir.mkdir(parents=True, exist_ok=True)
        proc = dict(self.process)
        proc["curr_bed_type"] = self.bed_type
        proc["enable_support"] = "1" if support else "0"
        for k, v in self.overrides.items():
            proc[k] = v
        paths = []
        for kind, d in (("machine", self.machine), ("process", proc), ("filament", self.filament)):
            p = outdir / f"{kind}.json"
            p.write_text(json.dumps(d, indent=1))
            paths.append(p)
        return tuple(paths)  # type: ignore

    def summary(self) -> dict:
        return {
            "machine": self.machine["name"], "process": self.process["name"],
            "filament": self.filament["name"], "bed_type": self.bed_type,
            "bed_mm": [*self.bed_xy, self.bed_z], "nozzle": self.nozzle, "layer": self.layer,
            "line_width": self.line_width, "support_angle_deg": self.support_angle,
            "filament_type": self.filament.get("filament_type", ["?"])[0],
            "overrides": self.overrides,
        }


def load(spec_printer: dict | None = None, material: str = "PETG") -> Printer:
    sp = spec_printer or {}
    mat = config.material(material)
    return Printer(
        machine=flatten("machine", sp.get("machine", "Bambu Lab X1 Carbon 0.4 nozzle")),
        process=flatten("process", sp.get("process", "0.20mm Standard @BBL X1C")),
        filament=flatten("filament", sp.get("filament", mat["preset"])),
        bed_type=sp.get("bed_type", "Textured PEI Plate"),
        overrides={k: str(v) for k, v in {**(config.load_yaml("print_defaults.yaml").get("overrides") or {}),
                                           **(sp.get("overrides") or {})}.items()},
    )
