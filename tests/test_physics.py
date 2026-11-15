"""MuJoCo physics must reproduce the closed-form follower-jump speed: a gravity-returned
flat follower leaves an eccentric cam when e·ω² > g  →  ω_jump = sqrt(g / e)."""
import math
import pytest

from forge import config, geometry, stages
from forge.project import Project

DESIGN = '''
from build123d import Box, Cylinder, Pos, Rot, Align
from forge.dsl import Design, Part, Motion
E, R, Z = {e}, 8.0, 20.0
def build(p):
    import math
    a = math.radians(p.crank)
    cam = Rot(0, 90, 0) * Cylinder(R, 6) + Rot(0, 90, 0) * Cylinder(2.5, 40)        # disc + shaft along X
    cam = Pos(0, -E, 0) * cam                                                       # offset: eccentric about X axis
    lift = -E * math.sin(a) + R + 0.1                                               # cam top under a flat foot
    fol = Pos(0, 0, 3) * Box(10, 10, 6) + Pos(0, 0, 14) * Box(4, 4, 18)
    return Design(parts=[Part("cam", cam, placement=((0, 0, Z), (p.crank, 0, 0))),
                         Part("fol", fol, placement=((0, 0, Z + lift), (0, 0, 0)))],
                  motion=Motion("crank", 0, 360, 15, min_travel_mm=1))
'''


@pytest.mark.parametrize("e", [3.5])
def test_follower_jump_speed_matches_theory(tmp_path, monkeypatch, e):
    from forge import physics
    monkeypatch.setattr(config, "PROJECTS", tmp_path)
    d = tmp_path / "cam"
    d.mkdir()
    (d / "spec.yaml").write_text("title: cam\nparams: {crank: 0}\n")
    (d / "design.py").write_text(DESIGN.format(e=e))
    p = Project("cam")
    geometry.build(p)
    fit = stages.fit(p)
    assert all(c['status'] != 'fail' for c in fit['checks']), fit['checks']   # the test mechanism itself must be valid
    rpm_theory = math.sqrt(9.81 / (e * 1e-3)) * 60 / (2 * math.pi)   # ≈ 505 rpm for e = 3.5 mm
    slow = physics.simulate(p, rpm=0.8 * rpm_theory, record=False)
    fast = physics.simulate(p, rpm=1.2 * rpm_theory, record=False)
    assert slow["validated"] and fast["validated"]
    assert not slow["metrics"]["fol"]["jumps"], slow["metrics"]
    assert fast["metrics"]["fol"]["jumps"], fast["metrics"]
