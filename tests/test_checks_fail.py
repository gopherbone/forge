"""Every check must be able to fail. Each test feeds a known-bad part and asserts the
check catches it, plus a known-good control so we know it isn't failing everything."""
import numpy as np
import pytest
import trimesh
from build123d import Align, Box, Cylinder, Pos

from forge import printer
from forge.checks import assembly, printability
from forge.dsl import Fit, Region
from forge.geometry import to_print_frame

A = (Align.CENTER, Align.CENTER, Align.MIN)


@pytest.fixture(scope="module")
def pr():
    return printer.load()


def mesh_of(shape):
    import tempfile, pathlib
    from build123d import export_stl
    p = pathlib.Path(tempfile.mkdtemp()) / "m.stl"
    export_stl(shape, p, tolerance=0.01)
    m = trimesh.load_mesh(p)
    return to_print_frame(m, (0, 0, 0))[0]


def run(shape, pr, **meta):
    checks, _ = printability.analyze(mesh_of(shape), pr, {"supports": "auto", "cosmetic": [], **meta}, (0, 0, 0))
    return {c["id"]: c for c in checks}


def test_good_block_passes(pr):
    c = run(Box(30, 30, 10, align=A), pr)
    assert all(v["status"] in ("pass", "info") for v in c.values()), {k: v["status"] for k, v in c.items()}


def test_t_shape_needs_support(pr):
    t = Box(10, 10, 20, align=A) + Pos(0, 0, 20) * Box(40, 10, 4, align=A)  # 15 mm flat overhangs each side
    c = run(t, pr)
    assert c["supports"]["status"] == "fail" and c["supports"]["value"] > 100   # zero-supports rule
    c = run(t, pr, supports="off")
    assert c["supports"]["status"] == "fail"


def test_short_bridge_is_not_support(pr):
    bridge = Box(30, 10, 10, align=A) - Box(8, 12, 6, align=A)  # 8 mm tunnel
    c = run(bridge, pr)
    assert c["supports"]["status"] == "pass"
    assert c["bridges"]["value"]


def test_thin_fin_fails_wall_check(pr):
    fin = Box(20, 20, 2, align=A) + Pos(0, 0, 2) * Box(20, 0.3, 15, align=A)
    c = run(fin, pr)
    assert c["wall_thickness"]["status"] == "fail"


def test_oversize_fails_bed_fit(pr):
    c = run(Box(300, 20, 10, align=A), pr)
    assert c["bed_fit"]["status"] == "fail"
    c = run(Box(250, 250, 10, align=A), pr)  # fits the plate but not with the 18x28 exclusion corner
    assert c["bed_fit"]["status"] == "fail"


def test_open_mesh_fails_manifold(pr):
    m = trimesh.creation.box((10, 10, 10))
    m.update_faces(np.arange(len(m.faces)) != 0)  # punch a hole
    checks, _ = printability.analyze(to_print_frame(m, (0, 0, 0))[0], pr, {"supports": "auto", "cosmetic": []}, (0, 0, 0))
    assert next(c for c in checks if c["id"] == "manifold")["status"] == "fail"


def test_tall_needle_warns(pr):
    c = run(Cylinder(2, 60, align=A), pr)
    assert c["tip_ratio"]["status"] == "warn"
    assert c["bed_contact"]["status"] == "warn"


def test_interference_and_tight_fit_fail():
    a = Box(20, 20, 10, align=A)
    b = Pos(5, 0, 0) * Box(20, 20, 10, align=A)
    r = assembly.run({"a": a, "b": b}, [])
    assert r[0]["status"] == "fail"
    peg = Cylinder(4, 10, align=A)
    hole = Box(20, 20, 10, align=A) - Cylinder(4.05, 10, align=A)  # 0.05 mm gap
    r = assembly.run({"peg": peg, "plate": hole}, [Fit("peg", "plate", "sliding")])
    assert r[0]["status"] == "fail" and "Too tight" in r[0]["detail"]
    hole_ok = Box(20, 20, 10, align=A) - Cylinder(4.2, 10, align=A)
    r = assembly.run({"peg": peg, "plate": hole_ok}, [Fit("peg", "plate", "sliding")])
    assert r[0]["status"] == "pass", r[0]


def test_presets_are_flattened(pr):
    s = pr.summary()
    assert s["bed_mm"] == [256.0, 256.0, 250.0]
    assert s["filament_type"] == "PETG"
    assert pr.density == pytest.approx(1.25)


def test_rounded_or_chamfered_edge_at_plate_warns(pr):
    from build123d import Axis
    filleted = Box(30, 30, 10, align=A)
    filleted = filleted.fillet(2.5, filleted.edges().group_by(Axis.Z)[0])
    assert run(filleted, pr)["bed_edge"]["status"] == "warn"
    chamfered = Box(30, 30, 10, align=A)
    chamfered = chamfered.chamfer(1.0, None, chamfered.edges().group_by(Axis.Z)[0])
    assert run(chamfered, pr)["bed_edge"]["status"] == "warn"   # 45° chamfers curled on the real snapbox print
    assert run(Box(30, 30, 10, align=A), pr)["bed_edge"]["status"] == "pass"
    from build123d import Sphere
    dome_down = Pos(0, 0, 8) * Sphere(10) & Box(40, 40, 30, align=A)  # sphere cut below its equator
    assert run(dome_down, pr)["bed_edge"]["status"] == "warn"


def _feat(shape, pr, euler=(0, 0, 0), fits=True):
    import tempfile, pathlib
    from build123d import export_step
    from forge.checks import features
    from forge.geometry import rot
    from forge import config
    p = pathlib.Path(tempfile.mkdtemp()) / "f.step"
    export_step(shape, p)
    m = to_print_frame(mesh_of(shape), euler)[0] if euler != (0, 0, 0) else mesh_of(shape)
    return {c["id"]: c for c in features.analyze(p, rot(euler), m, pr, config.rules(), fits)}


def test_feature_footguns(pr):
    from build123d import Axis, Rot
    block_h = Box(30, 20, 20, align=A) - Pos(0, 0, 10) * Rot(0, 90, 0) * Cylinder(3, 40)   # Ø6 hole along X
    assert _feat(block_h, pr)["horizontal_holes"]["status"] == "warn"
    block_v = Box(30, 20, 20, align=A) - Cylinder(3, 40)                                    # vertical Ø6 hole
    c = _feat(block_v, pr)
    assert c["horizontal_holes"]["status"] == "pass"
    assert c["first_layer_holes"]["status"] == "warn"                                       # it pierces the plate
    pin_up = Box(20, 20, 3, align=A) + Cylinder(1.5, 15, align=A)                          # Ø3×15 pin standing up
    c = _feat(pin_up, pr)
    assert c["upright_pins"]["status"] == "warn"
    assert c["slender_towers"]["status"] == "warn"
    small = Box(20, 20, 5, align=A) - Cylinder(1.0, 20)                                     # Ø2 vertical hole
    assert _feat(small, pr)["small_vertical_holes"]["status"] == "warn"
    plain = Box(20, 20, 5, align=A)
    c = _feat(plain, pr)
    assert all(v["status"] == "pass" for v in c.values()), {k: v["status"] for k, v in c.items()}


def test_print_defaults_applied(pr):
    assert pr.overrides.get("sparse_infill_pattern") == "gyroid"
    assert pr.overrides.get("sparse_infill_density") == "25%"


def test_sharp_vertical_corners_warn(pr):
    from build123d import Axis
    sharp = Box(60, 40, 6, align=A)
    assert _feat(sharp, pr)["sharp_corners"]["status"] == "warn"
    soft = Box(60, 40, 6, align=A)
    soft = soft.fillet(4, soft.edges().filter_by(Axis.Z))   # vertical edges filleted
    assert _feat(soft, pr)["sharp_corners"]["status"] == "pass"
    assert run(soft, pr)["bed_edge"]["status"] == "pass"     # vertical fillets are not 'rounds at the plate'


def test_hole_relief_step_is_not_a_bed_edge(pr):
    plate = Box(30, 30, 6, align=A) - Cylinder(3, 20) - Cylinder(3.3, 0.6, align=A)   # hole with a 0.6 mm stepped relief
    assert run(plate, pr)["bed_edge"]["status"] == "pass"
    lip = Box(30, 30, 6, align=A) - Box(30.0, 30.0, 0.6, align=A) + Pos(0, 0, 0) * Box(29, 29, 0.6, align=A)  # outer step at the plate
    assert run(lip, pr)["bed_edge"]["status"] == "warn"


def test_dome_on_top_warns_flat_passes(pr):
    from build123d import Sphere
    dome = Box(40, 40, 5, align=A) + (Pos(0, 0, 5) * Sphere(15) & Box(40, 40, 30, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Pos(0, 0, 5).location if hasattr(Pos(0,0,5),'location') else Pos(0,0,5)))
    assert run(dome, pr)["up_curves"]["status"] == "warn"
    flat = Box(40, 40, 5, align=A) + Pos(0, 0, 5) * Cylinder(12, 8, align=A)   # flat-topped cylinder: vertical walls + flat top
    assert run(flat, pr)["up_curves"]["status"] == "pass"


def test_supports_fail_unless_opted_in(pr):
    t = Box(10, 10, 20, align=A) + Pos(0, 0, 20) * Box(40, 10, 4, align=A)
    assert run(t, pr)["supports"]["status"] == "fail"
    assert run(t, pr, supports="on")["supports"]["status"] == "warn"


def test_undeclared_touching_parts_warn():
    a = Box(20, 20, 5, align=A)
    b = Pos(0, 0, 5) * Box(20, 20, 5, align=A)           # stacked, coplanar faces, no fit declared
    r = assembly.run({"a": a, "b": b}, [])
    assert r[0]["status"] == "warn" and "Touching" in r[0]["detail"]
    c = Pos(0, 0, 5.5) * Box(20, 20, 5, align=A)         # 0.5 mm gap
    assert assembly.run({"a": a, "c": c}, [])[0]["status"] == "pass"


def test_thin_z_gap_under_ceiling_warns(pr):
    # a slab hovering 0.4 mm (2 layers) over a base: the ceiling bridges and fuses
    base = Box(30, 30, 3, align=A)
    post = Pos(-12, 0, 3) * Box(4, 30, 5, align=A)
    slab = Pos(2, 0, 3.4) * Box(24, 30, 2, align=A)
    assert run(base + post + slab, pr)["z_fuse"]["status"] == "warn"
    slab_ok = Pos(2, 0, 3.8) * Box(24, 30, 2, align=A)         # 0.8 mm = 4 layers
    assert run(base + post + slab_ok, pr)["z_fuse"]["status"] == "pass"
