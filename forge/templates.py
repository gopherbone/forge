"""`forge new` scaffold."""
from __future__ import annotations

from .config import ForgeError
from .project import Project

SPEC = """# {title}: design spec. The human approves this at the `spec` gate.
title: {title}
summary: >
  One or two sentences: what this is, who uses it, where it lives.

requirements:            # numbered, testable. Each one should map to a check or a load case.
  - id: R1
    text: "Describe a measurable requirement (size, load, fit, motion)."
    verify: "check | fit | sim:<load case> | slice | human"

loads:                   # real-world loads in words; design.py turns them into LoadCases
  - "e.g. 20 N pressed on the lid centre (a hand leaning on it)"

material: PETG
cosmetic: "Which faces people see. Those faces avoid supports and seams."
constraints:
  - "Fits on the X1C plate (256 x 256 x 250 mm)"
  - "Support-free unless a reason is logged in the journal"

open_questions: []       # anything the agent needs a human to decide. Shown at the top of the traveller.

params:                  # every dimension design.py uses, in mm. Change here, not in code.
  width: 40
  depth: 30
  height: 20

printer:
  machine: "Bambu Lab X1 Carbon 0.4 nozzle"
  process: "0.20mm Standard @BBL X1C"
  bed_type: "Textured PEI Plate"
  overrides: {{}}        # e.g. {{wall_loops: 3}} applied on top of the process preset
"""

DESIGN = '''"""{title}: parametric design. All dimensions come from spec.yaml `params` (p.*).

Design-for-FDM rules this file should follow (see CLAUDE.md):
- Overhangs no shallower than 45° from horizontal (the slicer supports < 30°)
- Walls ≥ 2 lines (0.84 mm), better ≥ 1.6 mm; flexures thin but ≥ 3 lines
- Chamfer bed-side edges 0.4-0.6 mm (elephant foot); fillet top edges for feel
- Holes in vertical walls: teardrop or ≤ 8 mm; flat bridges ≤ 12 mm
- Clearances come from forge/data/fits.yaml, never hard-coded
"""
from build123d import *

from forge.config import fits_table
from forge.dsl import Design, Fit, LoadCase, Part, Region


def build(p) -> Design:
    gap = fits_table()["sliding"]["gap"]  # noqa: F841  (example of pulling a clearance)
    body = extrude(RectangleRounded(p.width, p.depth, 4), p.height)
    body = body.fillet(0.8, body.edges().group_by(Axis.Z)[-1])
    return Design(parts=[Part("body", body, cosmetic=["+z"])])
'''


def scaffold(name: str, title: str) -> Project:
    proj = Project(name)
    if proj.dir.exists():
        raise ForgeError(f"{proj.dir} already exists")
    proj.dir.mkdir(parents=True)
    (proj.dir / "spec.yaml").write_text(SPEC.format(title=title))
    (proj.dir / "design.py").write_text(DESIGN.format(title=title))
    (proj.dir / "journal.md").write_text(f"# Journal: {title}\n\nDecisions, findings and human comments, newest last.\n")
    proj.journal("project created", author="forge")
    return proj
