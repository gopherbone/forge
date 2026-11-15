"""FEA must reproduce closed-form beam theory before anyone trusts it."""
import numpy as np
import pytest
from build123d import Box, Align, export_step

from forge import config
from forge.dsl import LoadCase, Region
from forge.sim import fea

MAT = {"E_mpa": 1460.0, "poisson": 0.38, "strength_xy_mpa": 48, "strength_z_mpa": 35,
       "strain_allow_once": 0.035, "strain_allow_repeated": 0.02, "strain_allow_z_factor": 0.6}
L, B, H = 100.0, 10.0, 10.0


@pytest.fixture(scope="module")
def beam(tmp_path_factory):
    d = tmp_path_factory.mktemp("beam")
    p = d / "beam.step"
    export_step(Box(L, B, H, align=Align.MIN), p)
    return d, p


def _lc(**kw):
    return LoadCase("c", "beam", fixed=Region((-1, -1, -1), (0.01, B + 1, H + 1)),
                    load=Region((L - 0.01, -1, -1), (L + 1, B + 1, H + 1)), **kw)


def test_linear_cantilever_matches_beam_theory(beam):
    d, step = beam
    F = 10.0
    r = fea.solve(step, _lc(force=(0, 0, -F)), MAT, d / "lin", size=2.5)
    I = B * H ** 3 / 12
    G = MAT["E_mpa"] / (2 * (1 + MAT["poisson"]))
    euler = F * L ** 3 / (3 * MAT["E_mpa"] * I)
    timoshenko = euler + F * L / ((5 / 6) * G * B * H)
    got = r["load_disp_mm"]  # reported along the load direction
    assert got == pytest.approx(timoshenko, rel=0.04), (got, euler, timoshenko)
    # bending stress at root: M c / I (excluding the singular fixed nodes it should be close)
    ev = fea.evaluate(r["_field"], np.eye(3), MAT, "static", r["_field"]["fixed"])
    sigma = F * L * (H / 2) / I
    assert ev["von_mises_max_mpa"] == pytest.approx(sigma, rel=0.25)


def test_nonlinear_large_deflection_stiffens(beam):
    """Big tip displacement: NLGEOM force must differ from linear (membrane stiffening
    is negligible for a free-end cantilever, but foreshortening changes the curve), and
    the curve must be monotonic and have `steps` points."""
    d, step = beam
    disp = 30.0
    lin = fea.solve(step, _lc(displacement=(0, 0, -disp)), MAT, d / "dl", size=3.0)
    nl = fea.solve(step, _lc(displacement=(0, 0, -disp), nonlinear=True, steps=6), MAT, d / "dn", size=3.0)
    f_lin, f_nl = abs(lin["load_force_n"]), abs(nl["load_force_n"])
    assert len(nl["curve"]) >= 7
    fs = [abs(p[1]) for p in nl["curve"]]
    assert all(b >= a for a, b in zip(fs, fs[1:]))
    assert abs(f_nl - f_lin) / f_lin > 0.01, (f_lin, f_nl)


def test_displacement_control_does_not_lock_rotation(tmp_path):
    """Imposed displacement on a contact line must give the same stiffness as a force on
    that line. Prescribing each node directly locked rotation and read 2.8x too stiff."""
    from build123d import Box, Align, export_step
    Lb, b, t = 15.5, 7.0, 1.4
    step = tmp_path / "arm.step"
    export_step(Box(t, b, Lb + 3, align=Align.MIN), step)
    fixed = Region((-1, -1, Lb + 3 - 0.01), (t + 1, b + 1, Lb + 4))
    line = Region((t - 0.01, -1, 2.7), (t + 0.01, b + 1, 3.3))
    rf = fea.solve(step, LoadCase("f", "a", fixed=fixed, load=line, force=(-0.5, 0, 0)), MAT, tmp_path / "f", 0.35)
    rd = fea.solve(step, LoadCase("d", "a", fixed=fixed, load=line, displacement=(-0.5, 0, 0), nonlinear=True, steps=4),
                   MAT, tmp_path / "d", 0.35)
    k_force = rf["load_force_n"] / rf["load_disp_mm"]
    k_disp = rd["load_force_n"] / rd["load_disp_mm"]
    k_beam = 3 * MAT["E_mpa"] * b * t ** 3 / 12 / Lb ** 3
    assert k_disp == pytest.approx(k_force, rel=0.08), (k_disp, k_force)
    assert k_disp == pytest.approx(k_beam, rel=0.15), (k_disp, k_beam)
    assert len(rd["curve"]) >= 5  # per-increment force-deflection points are printed


def test_root_strain_and_layer_knockdown(tmp_path):
    """Flexure verdicts use principal strain and across-layer stress, so validate both:
    root strain vs 1.5*d*t/L^2, and rotating the print frame moves bending tension into Z."""
    from build123d import Box, Align, export_step
    from forge.geometry import rot
    Lb, b, t = 30.0, 6.0, 2.0
    step = tmp_path / "arm.step"
    export_step(Box(t, b, Lb + 3, align=Align.MIN), step)
    fixed = Region((-1, -1, Lb + 3 - 0.01), (t + 1, b + 1, Lb + 4))
    line = Region((t - 0.01, -1, 2.7), (t + 0.01, b + 1, 3.3))
    d = 1.0
    r = fea.solve(step, LoadCase("s", "a", fixed=fixed, load=line, displacement=(-d, 0, 0)), MAT, tmp_path / "s", 0.4)
    f = r["_field"]
    ev_flat = fea.evaluate(f, np.eye(3), MAT, "once", f["exclude"])          # arm axis = build Z: bends across layers
    ev_side = fea.evaluate(f, rot((0, 90, 0)), MAT, "once", f["exclude"])     # arm axis horizontal: bends in-layer
    expected = 1.5 * d * t / Lb ** 2
    assert ev_flat["strain_max"] == pytest.approx(expected, rel=0.25), (ev_flat["strain_max"], expected)
    assert ev_flat["interlayer_tension_max_mpa"] > 5 * max(ev_side["interlayer_tension_max_mpa"], 1e-6) or \
        ev_side["interlayer_tension_max_mpa"] < 0.2 * ev_flat["interlayer_tension_max_mpa"]
    assert ev_flat["strain_util"] > ev_side["strain_util"]


FEEL = '''
from build123d import Box, Align
from forge.dsl import Design, Part, LoadCase, Region
def build(p):
    arm = Box(1.6, 8, 20, align=Align.MIN)
    return Design(parts=[Part("arm", arm)], loads=[LoadCase("snap", "arm",
        fixed=Region((-1, -1, 19.99), (3, 9, 21)), load=Region((1.59, -1, 1.7), (1.61, 9, 2.3)),
        displacement=(-1.0, 0, 0), nonlinear=True, use="repeated", steps=4, mesh_size=0.8, uniform=True,
        min_force_n=p.fmin, max_force_n=p.fmax)])
'''


@pytest.mark.parametrize("fmin,fmax,want", [(0.05, 20, "pass"), (5, 15, "fail")])
def test_snap_feel_force_check(tmp_path, monkeypatch, fmin, fmax, want):
    """A thin 20 mm arm pushed 1 mm needs ~0.2 N: fine for a 0.05-20 N window, too weak to feel for 5-15 N."""
    from forge import config, geometry, stages
    from forge.project import Project
    monkeypatch.setattr(config, "PROJECTS", tmp_path)
    d = tmp_path / f"feel{int(fmin)}"
    d.mkdir()
    (d / "spec.yaml").write_text(f"title: f\nparams: {{fmin: {fmin}, fmax: {fmax}}}\n")
    (d / "design.py").write_text(FEEL)
    p = Project(d.name)
    geometry.build(p)
    r = stages.sim(p, converge=False)
    c = next(c for c in r["cases"][0]["checks"] if c["id"].startswith("feel:"))
    assert c["status"] == want, c
