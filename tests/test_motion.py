"""The motion sweep must catch a collision that only happens mid-cycle."""
import pytest

from forge import config, geometry, stages
from forge.project import Project

DESIGN = '''
from build123d import Box, Cylinder, Pos, Align
from forge.dsl import Design, Part, Motion
def build(p):
    arm = Pos(p.arm_len / 2, 0, 0) * Box(p.arm_len, 4, 4)
    post = Pos(0, 18, 0) * Cylinder(3, 10)          # sits at 90 degrees around the pivot
    hub = Cylinder(1, 6)
    return Design(parts=[Part("arm", arm, placement=((0, 0, 0), (0, 0, p.ang))), Part("post", post),
                         Part("hub", Pos(-30, 0, 0) * hub)],
                  motion=Motion("ang", 0, 360, 15, min_travel_deg=20))
'''


def make(tmp_path, monkeypatch, arm_len):
    monkeypatch.setattr(config, "PROJECTS", tmp_path)
    d = tmp_path / f"m{arm_len}"
    d.mkdir()
    (d / "spec.yaml").write_text(f"title: m\nparams: {{arm_len: {arm_len}, ang: 0}}\n")
    (d / "design.py").write_text(DESIGN)
    p = Project(d.name)
    geometry.build(p)
    return p


def test_sweep_catches_mid_cycle_collision(tmp_path, monkeypatch):
    p = make(tmp_path, monkeypatch, 25)   # arm reaches the post at ~90 deg, clear at 0 deg
    r = stages.fit(p)
    bad = [c for c in r["checks"] if c["id"] == "sweep:arm|post"]
    assert bad and bad[0]["status"] == "fail", r["checks"]
    assert r["motion"]["travel"]["arm"]["rotation_deg"] > 170


def test_sweep_passes_clear_mechanism(tmp_path, monkeypatch):
    p = make(tmp_path, monkeypatch, 12)   # too short to reach the post
    r = stages.fit(p)
    assert all(c["status"] != "fail" for c in r["checks"]), r["checks"]
    assert any(c["id"] == "travel:arm" and c["status"] == "pass" for c in r["checks"])


ENGAGE = '''
from build123d import Box, Cylinder, Pos, Rot
from forge.dsl import Design, Part, Motion, Fit
import math
def build(p):
    a = math.radians(p.crank)
    cam = Pos(0, -3, 0) * (Rot(0, 90, 0) * Cylinder(p.cam_r, 6))
    top = -3 * math.sin(a) + 8.0 + 0.1          # follower rides where an R=8 cam would put it
    fol = Pos(0, 0, 3) * Box(10, 10, 6)
    return Design(parts=[Part("cam", cam, placement=((0, 0, 20), (p.crank, 0, 0))),
                         Part("fol", fol, placement=((0, 0, 20 + top), (0, 0, 0)))],
                  fits=[Fit("cam", "fol", "contact", drives=True, retention="captured")],
                  motion=Motion("crank", 0, 360, 30))
'''


def _engage(tmp_path, monkeypatch, cam_r):
    monkeypatch.setattr(config, "PROJECTS", tmp_path)
    d = tmp_path / f"e{int(cam_r)}"
    d.mkdir()
    (d / "spec.yaml").write_text(f"title: e\nparams: {{crank: 0, cam_r: {cam_r}}}\n")
    (d / "design.py").write_text(ENGAGE)
    p = Project(d.name)
    geometry.build(p)
    return {c["id"]: c for c in stages.fit(p)["checks"]}


def test_driver_that_never_reaches_fails(tmp_path, monkeypatch):
    assert _engage(tmp_path, monkeypatch, 8.0)["engage:cam|fol"]["status"] == "pass"
    assert _engage(tmp_path, monkeypatch, 5.0)["engage:cam|fol"]["status"] == "fail"   # cam too small: never touches


NEAR = '''
from build123d import Box, Pos
from forge.dsl import Design, Part, Motion
def build(p):
    a = Box(10, 10, 10)
    b = Pos(10.05 - 0.04 * abs(p.t - 180) / 180 * 0 + (0.0 if p.t < 180 else 2.0), 0, 0) * Box(10, 10, 10)  # 0.05 mm away for half the cycle
    return Design(parts=[Part("a", a), Part("b", b, placement=((0, 0, 0), (0, 0, 0)))], motion=Motion("t", 0, 360, 45))
'''


def test_sweep_warns_on_undeclared_near_touch(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS", tmp_path)
    d = tmp_path / "near"
    d.mkdir()
    (d / "spec.yaml").write_text("title: near\nparams: {t: 0}\n")
    (d / "design.py").write_text(NEAR)
    p = Project("near")
    geometry.build(p)
    c = next(c for c in stages.fit(p)["checks"] if c["id"] == "sweep:a|b")
    assert c["status"] == "warn" and "rub" in c["detail"]
