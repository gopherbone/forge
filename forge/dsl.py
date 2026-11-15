"""The vocabulary a project's design.py uses to describe an assembly.

    from build123d import *
    from forge.dsl import Design, Part, Fit, LoadCase, Region

    def build(p) -> Design:
        base = Box(p.w, p.d, p.h) - ...
        return Design(
            parts=[Part("base", base, cosmetic=["+z", "-y"])],
            fits=[Fit("base", "lid", "sliding", region=Region((..), (..)))],
            loads=[LoadCase("hook_snap", part="base", fixed=Region(...), load=Region(...),
                            displacement=(0.9, 0, 0), nonlinear=True, use="repeated")],
        )

All coordinates are millimetres in the PART frame (the frame the part was modelled in).
`placement` moves a part into the assembly frame; `orient` rotates it onto the print bed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Sequence

Vec = tuple[float, float, float]


@dataclass
class Region:
    """Axis-aligned box. Selects mesh nodes (FEA) or limits a fit check to an area."""
    min: Vec
    max: Vec

    def contains(self, pts):
        import numpy as np
        lo, hi = np.asarray(self.min) - 1e-6, np.asarray(self.max) + 1e-6
        return np.all((pts >= lo) & (pts <= hi), axis=1)


def select(regions, pts):
    """Nodes inside a Region or inside any of a list of Regions."""
    import numpy as np
    if isinstance(regions, Region):
        return regions.contains(pts)
    mask = np.zeros(len(pts), dtype=bool)
    for r in regions:
        mask |= r.contains(pts)
    return mask


@dataclass
class Part:
    name: str
    shape: Any                                  # build123d Part/Solid/Compound
    material: str = "PETG"
    color: str | None = None                    # hex, for renders
    placement: Vec | tuple[Vec, Vec] = (0, 0, 0)  # translation, or (translation, euler_deg) into assembly
    orient: Vec | None = None                   # euler XYZ degrees onto the bed; None = let `forge orient` choose
    cosmetic: Sequence[str] = ()                # part-frame directions of show faces, e.g. ["+z", "-y"]
    supports: Literal["auto", "on", "off"] = "auto"
    bodies: int = 1                             # expected separate bodies (e.g. a set of pegs printed together)
    purchased: bool = False                     # bought hardware (steel dowel, bushing, insert): included in fit and motion, not printed
    notes: str = ""


@dataclass
class Fit:
    """A declared relationship between two parts in the assembly.
    kind: a key of forge/data/fits.yaml (press, snug, sliding, loose, print_in_place, contact)
    region: limit the clearance measurement to this assembly-frame box (optional).
    overlap_ok_mm3: for press/snap fits, the interference volume that is intended."""
    a: str
    b: str
    kind: str
    region: Region | None = None
    overlap_ok_mm3: float = 0.0
    retention: Literal["snap", "captured", "press", "gravity", "none"] | None = None  # how the joint stays together
    snap_case: str | None = None          # for retention="snap": the LoadCase that verifies the snap (strain + feel)
    drives: bool = False                  # a driving pair (cam/follower, pinion/rack, blade/tooth): the sweep must show real engagement
    notes: str = ""


@dataclass
class LoadCase:
    """A static load on one part, fixed somewhere, loaded somewhere else.
    Give either `force` (N, total, spread over the load region's nodes) or
    `displacement` (mm, imposed on the load region; use this for snap fits / flexures:
    the reaction force comes out as a result). Part frame.
    nonlinear: geometric nonlinearity (large deflection). Always on for flexures.
    use: 'static' (strength check), 'once' or 'repeated' (strain check for flexures)."""
    name: str
    part: str
    fixed: Region | list[Region]
    load: Region | list[Region]
    force: Vec | None = None
    displacement: Vec | None = None
    nonlinear: bool = False
    use: Literal["static", "once", "repeated"] = "static"
    steps: int = 10
    mesh_size: float | None = None        # element size in the refined zone (default: from wall thickness)
    refine: Region | list[Region] | None = None  # zone(s) meshed at mesh_size; default: load region grown by 8 mm
    uniform: bool = False                 # mesh the whole part at mesh_size (no local refinement)
    min_force_n: float | None = None      # feel targets for snaps/detents: below this, nobody notices the click
    max_force_n: float | None = None      # ...above this, it's a struggle to assemble or operate
    notes: str = ""


@dataclass
class Motion:
    """A mechanism's driving parameter. design.py places moving parts from p.<param>;
    `forge fit` rebuilds the design at every value from start to stop (exclusive) by step."""
    param: str
    start: float = 0.0
    stop: float = 360.0
    step: float = 15.0
    min_travel_mm: float = 0.0       # each moving part should travel at least this far...
    min_travel_deg: float = 0.0      # ...or rotate at least this much (requirement checks)
    exclude_travel: tuple = ()       # parts that move but don't need visible travel (e.g. the shaft)


@dataclass
class Design:
    parts: list[Part]
    fits: list[Fit] = field(default_factory=list)
    loads: list[LoadCase] = field(default_factory=list)
    explode: dict[str, Vec] = field(default_factory=dict)  # optional exploded-view offsets
    motion: Motion | None = None

    def part(self, name: str) -> Part:
        for p in self.parts:
            if p.name == name:
                return p
        raise KeyError(name)

    def describe(self) -> dict:
        def strip(o):
            d = asdict(o)
            d.pop("shape", None)
            return d
        return {
            "parts": [strip(p) for p in self.parts],
            "fits": [asdict(f) for f in self.fits],
            "loads": [asdict(l) for l in self.loads],
            "motion": asdict(self.motion) if self.motion else None,
        }
