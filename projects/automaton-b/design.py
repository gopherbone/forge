"""Frog Automaton, concept B: "Leapfrog Pond".

Three frogs on lily pads hop up and down in a wave as the side crank turns.

Mechanism
- `base`: open-bottom pond box. The top deck carries three keyed guide sleeves; the end walls
  carry the camshaft bearings (thickened by internal ribs). Printed deck-down (flat pond face on
  the textured plate), so the lily pads and ripples are V-grooves engraved into the deck.
- `crankshaft`: D-flat shaft + crank arm + knob in one piece, printed lying on the D-flat.
- `camblock`: three eccentric discs on one D-bored hub, phased 120 deg apart. Printed on end;
  45 deg cones under the upper two discs make it support-free.
- `follower_i`: flat foot (rides on the cam, and is the stop under the guide sleeve) + keyed
  rectangular rod. Inserted from below.
- `frog_i`: chubby frog with a keyed socket in its belly, pressed onto the rod top.

Kinematics (exact): a flat-faced follower on a round eccentric rests on the disc's top point,
so its foot sits at  z = shaft_z + cam_e * sin(phi_i + crank_deg) + cam_r + cam_follow_gap.

Every dimension is a p.<param> from spec.yaml. The frog is sculpted in "frog units"
(p.frog_w / FROG_W_UNITS); FROG holds dimensionless proportions, not dimensions.
"""
from math import cos, radians, sin, sqrt

from build123d import *

from forge.config import fits_table
from forge.dsl import Design, Fit, Motion, Part, Region

# ---------------------------------------------------------------- frog proportions
# Frog frame: belly flat at z=0, rod axis on the origin, the frog faces -Y.
# Values are in frog units (1 unit = p.frog_w / FROG_W_UNITS mm). Ellipsoids: (rx, ry, rz, cx, cy, cz).
# Each ellipsoid that reaches the bed is cut at |cz/rz| <= rz/sqrt(ry^2+rz^2) so its underside stays >= 45 deg.
FROG_W_UNITS = 18.4
FROG = {
    "body":   (7.2, 8.5, 6.5, 0.0, 1.0, 3.5),
    "head":   (7.0, 6.0, 5.0, 0.0, -4.5, 8.5),
    "haunch": (2.8, 5.5, 4.0, 6.4, 2.5, 2.2),     # mirrored in x
    "hand":   (2.0, 3.2, 1.5, 4.2, -6.8, 0.6),     # front feet, mirrored in x; ~3 mm junction with the body
    "eye":    (2.9, 3.8, -5.2, 12.6),             # sphere r, x, y, z (mirrored)
    "pupil":  (1.3, 3.9, -7.7, 13.2),
    "mouth":  (0.75, 6.6, 8.0, 68.0),             # groove r, z at front, z at corners, half-span deg
}


POLE_TRIM = 0.01   # mm shaved off sphere poles: OCC tessellates the degenerate pole as a non-manifold fan

# Reed clump layout on the front wall: (side of centre, pitch steps inward, height x reed_h, lean x reed_lean).
REEDS = ((-1, 0, 1.0, -1.0), (-1, 1, 1.3, 0.5), (-1, 2, 0.8, 1.0), (1, -1, 0.9, -0.7), (1, 0, 0.65, 0.5))


def _ellipsoid(rx, ry, rz, cx, cy, cz):
    e = scale(Sphere(1), by=(rx, ry, rz)) & Box(2 * rx + 1, 2 * ry + 1, 2 * (rz - POLE_TRIM))
    return Pos(cx, cy, cz) * e


def _xcyl(r, x0, x1, y=0.0, z=0.0):
    """Cylinder along X from x0 to x1."""
    return Pos((x0 + x1) / 2, y, z) * Cylinder(r, x1 - x0, rotation=(0, 90, 0))


def _halfspace_above(z, big=400):
    return Pos(0, 0, z + big / 2) * Box(big, big, big)


def _vring(a, b, w, top, at=(0, 0)):
    """V-groove (45 deg walls, depth w/2) along an ellipse with semi-axes a, b,
    opening w wide at z=top. Engraved into a face that prints on the bed: no ceilings."""
    d = w / 2
    o = extrude(Plane.XY.offset(top) * Ellipse(a + d, b + d), amount=-d, taper=45)
    i = extrude(Plane.XY.offset(top) * Ellipse(a - d, b - d), amount=-d, taper=-45)
    return Pos(at[0], at[1], 0) * (o - i)


def _vline(p0, p1, w, top):
    """Straight V-groove from p0 to p1 (xy) opening w wide at z=top."""
    (x0, y0), (x1, y1) = p0, p1
    L = sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
    d = w / 2
    tri = Plane.YZ * Polygon((-d, top), (d, top), (0, top - d), align=None)
    prism = extrude(tri, amount=L)                      # along +X from x=0
    from math import atan2, degrees
    return Pos(x0, y0, 0) * Rot(0, 0, degrees(atan2(y1 - y0, x1 - x0))) * prism


# ---------------------------------------------------------------- derived layout
def _layout(p):
    sn = fits_table()["snug"]["gap"]
    sl = fits_table()["sliding"]["gap"]
    lo = fits_table()["loose"]["gap"]
    xs = [(i - 1) * p.frog_pitch for i in range(3)]
    phis = [90.0 - 120.0 * i for i in range(3)]          # frog i peaks at crank_deg = 120*i: a wave
    zf_min = p.shaft_z - p.cam_e + p.cam_r + p.cam_follow_gap
    frog_dz = p.base_h + p.belly_gap - zf_min            # frog belly above foot bottom
    rod_top = frog_dz + p.socket_depth - sn
    x_in = p.base_w / 2 - p.wall                         # inner face of an end wall
    return dict(sn=sn, sl=sl, lo=lo, xs=xs, phis=phis, zf_min=zf_min, frog_dz=frog_dz,
                rod_top=rod_top, x_in=x_in, x_rib=x_in - p.bearing_rib_t)


def _foot_z(p, phi):
    """Exact follower foot height for an eccentric round cam under a flat foot."""
    return p.shaft_z + p.cam_e * sin(radians(phi + p.crank_deg)) + p.cam_r + p.cam_follow_gap


# ---------------------------------------------------------------- parts
def make_base(p, L):
    W, D, H = p.base_w, p.base_d, p.base_h
    shell = extrude(RectangleRounded(W, D, p.corner_r), H)
    # bed edge (deck perimeter, printed deck-down): chamfer against elephant foot
    shell = shell.chamfer(p.base_top_chamfer, None, shell.edges().group_by(Axis.Z)[-1])
    # open-bottom rim (prints on top): round it for the hand
    shell = shell.fillet(p.base_rim_fillet, shell.edges().group_by(Axis.Z)[0])
    cav = Pos(0, 0, -1) * extrude(RectangleRounded(W - 2 * p.wall, D - 2 * p.wall, p.corner_r - p.wall),
                                  H - p.deck_t + 1)
    base = shell - cav
    # bearing ribs on the inner faces of the end walls (full height: no overhangs)
    rib_h = H - p.deck_t
    for s in (-1, 1):
        base += Pos(s * (L["x_in"] - p.bearing_rib_t / 2 + 0.05), 0, rib_h / 2) * Box(p.bearing_rib_t + 0.1, p.bearing_rib_w, rib_h)
    # guide sleeves under the deck
    gx, gy = p.rod_a + 2 * L["sl"], p.rod_b + 2 * L["sl"]
    sx, sy = gx + 2 * p.guide_wall, gy + 2 * p.guide_wall
    sleeve_h = p.guide_len - p.deck_t + 0.1
    for x in L["xs"]:
        base += Pos(x, 0, H - p.guide_len + sleeve_h / 2) * Box(sx, sy, sleeve_h)
    # keyed guide holes
    for x in L["xs"]:
        base -= Pos(x, 0, H - p.guide_len - 1) * extrude(RectangleRounded(gx, gy, p.rod_corner_r + L["sl"]), p.guide_len + 2)
    # bearing holes (horizontal, < 8 mm: print round)
    base -= _xcyl(p.shaft_d / 2 + L["lo"], -W / 2 - 1, W / 2 + 1, 0, p.shaft_z)
    # pond engraving on the deck top: lily-pad rims with a notch, and ripples
    gw = p.groove_w
    tool = None
    for i, x in enumerate(L["xs"]):
        g = _vring(p.pad_rx, p.pad_ry, gw, H, (x, 0))
        a0 = radians(p.pad_notch_deg + (i - 1) * p.pad_notch_step)   # each pad's notch turned a little
        for da in (-p.pad_notch_half_deg, p.pad_notch_half_deg):
            a = a0 + radians(da)
            r0 = p.pad_notch_r0
            g += _vline((x + r0 * cos(a), r0 * sin(a)),
                        (x + (p.pad_rx - gw / 2) * cos(a), (p.pad_ry - gw / 2) * sin(a)), gw, H)
        tool = g if tool is None else tool + g
    for (cx, cy) in ((p.ripple_x, -p.ripple_y), (-p.ripple_x, p.ripple_y)):
        for r in (p.ripple_r, p.ripple_r + p.ripple_step):
            tool += _vring(r, r, gw, H, (cx, cy))
    base -= tool
    # reeds: raised leaves on the front wall, growing from the bottom edge
    for (side, k, hk, lk) in REEDS:
        x0, h, lean = side * p.reed_x + k * p.reed_pitch, hk * p.reed_h, lk * p.reed_lean
        w = p.reed_w / 2
        leaf = Polygon((x0 - w, 0), (x0 + w, 0), (x0 + w * 1.1 + lean * 0.5, h * 0.5), (x0 + lean, h),
                       (x0 - w * 0.9 + lean * 0.5, h * 0.5), align=None)
        base += extrude(Plane.XZ.offset(D / 2 - 0.2) * leaf, p.reed_t + 0.2)
    return base


def make_crankshaft(p, L):
    """Part frame: shaft axis = X through the origin. D-flat on -Z; the whole part is cut on the
    D-flat plane so it prints lying on it, support-free."""
    r = p.shaft_d / 2
    x0 = -p.base_w / 2 + p.shaft_end_inset
    xh = p.base_w / 2 + p.hub_gap
    xa = xh + p.crank_t
    hub = _xcyl(p.crank_hub_r, xh, xa)
    arm = Pos(xh, 0, 0) * extrude(Plane.YZ * Pos(p.crank_r / 2, 0) * SlotCenterToCenter(p.crank_r, p.crank_arm_w), p.crank_t)
    knob = _xcyl(p.knob_d / 2, xa - 0.5, xa + p.knob_l, p.crank_r, 0)
    knob = knob.fillet(p.knob_tip_r, knob.edges().sort_by(Axis.X)[-1:])
    crank = hub + arm + knob
    try:
        crank = crank.fillet(p.crank_edge_r, crank.edges().filter_by_position(Axis.X, xa - 0.01, xa + 0.01))
    except Exception:
        pass
    shaft = _xcyl(r, x0, xh + 0.5)
    shaft = shaft.chamfer(p.shaft_lead_chamfer, None, shaft.edges().sort_by(Axis.X)[:1])
    part = (shaft + crank) & _halfspace_above(-(r - p.shaft_flat))
    try:    # bed-edge chamfer (elephant foot) around the whole flat
        part = part.chamfer(p.bed_chamfer, None, part.edges().group_by(Axis.Z)[0])
    except Exception:
        pass
    return part


def make_camblock(p, L):
    """Part frame: shaft axis = X through the origin. Disc i centre at (y, z) = e(cos phi_i, sin phi_i)."""
    c = p.cam_chamfer
    x_lo = L["xs"][0] - p.cam_w / 2
    x_hi = L["x_rib"] - p.cam_end_gap
    blk = _xcyl(p.cam_hub_r, x_lo, x_hi)
    cone_len = p.cam_e + p.cam_r - c - p.cam_hub_r + p.cam_cone_extra     # >= 45 deg everywhere
    for i, (x, phi) in enumerate(zip(L["xs"], L["phis"])):
        cy, cz = p.cam_e * cos(radians(phi)), p.cam_e * sin(radians(phi))
        disc = _xcyl(p.cam_r, x - p.cam_w / 2, x + p.cam_w / 2, cy, cz)
        disc = disc.chamfer(c, None, disc.edges().filter_by(GeomType.CIRCLE))
        blk += disc
        if i > 0:   # upper discs (print frame) need a cone under them
            xa = x - p.cam_w / 2
            cone = loft([Plane.YZ.offset(xa - cone_len) * Circle(p.cam_hub_r),
                         Plane.YZ.offset(xa) * Pos(cy, cz) * Circle(p.cam_r - c)])
            blk += cone
    bore = _xcyl(p.shaft_d / 2 + L["sn"], x_lo - 1, x_hi + 1) & _halfspace_above(-(p.shaft_d / 2 - p.shaft_flat + L["sn"]))
    return blk - bore


def make_follower(p, L):
    """Part frame: foot bottom centre at the origin."""
    foot = extrude(RectangleRounded(p.foot_w, p.foot_d, p.foot_corner_r), p.foot_t)
    foot = foot.chamfer(p.bed_chamfer, None, foot.edges().group_by(Axis.Z)[0])
    foot = foot.fillet(p.foot_top_r, foot.edges().group_by(Axis.Z)[-1])
    rod = Pos(0, 0, p.foot_t - 0.01) * extrude(RectangleRounded(p.rod_a, p.rod_b, p.rod_corner_r), L["rod_top"] - p.foot_t + 0.01)
    rod = rod.chamfer(p.rod_tip_chamfer, None, rod.edges().group_by(Axis.Z)[-1])
    f = foot + rod
    try:
        f = f.fillet(p.rod_root_r, f.edges().filter_by_position(Axis.Z, p.foot_t - 0.02, p.foot_t + 0.02)
                     .filter_by(lambda e: abs(e.center().X) < p.rod_a and abs(e.center().Y) < p.rod_b))
    except Exception:
        pass
    return f


def make_frog(p, L):
    u = p.frog_w / FROG_W_UNITS

    def E(rx, ry, rz, cx, cy, cz):
        return _ellipsoid(rx * u, ry * u, rz * u, cx * u, cy * u, cz * u)

    def S(r, x, y, z):
        return _ellipsoid(r * u, r * u, r * u, x * u, y * u, z * u)

    frog = E(*FROG["body"]) + E(*FROG["head"])
    for s in (-1, 1):
        rx, ry, rz, cx, cy, cz = FROG["haunch"]
        frog += E(rx, ry, rz, s * cx, cy, cz)
        rx, ry, rz, cx, cy, cz = FROG["hand"]
        frog += E(rx, ry, rz, s * cx, cy, cz)
        r, x, y, z = FROG["eye"]
        frog += S(r, s * x, y, z)
        r, x, y, z = FROG["pupil"]
        frog += S(r, s * x, y, z)
    # wide grin: a tube swept along the head surface, corners turned up, dimpled ends
    hrx, hry, hrz, hcx, hcy, hcz = FROG["head"]
    mr, zf, zc, span = FROG["mouth"]
    pts = []
    n = 11
    for k in range(n):
        t = radians(-span + 2 * span * k / (n - 1))
        z = zf + (zc - zf) * (1 - cos(t)) / (1 - cos(radians(span)))
        kk = sqrt(max(1 - ((z - hcz) / hrz) ** 2, 0.0))
        pts.append(((hcx + hrx * kk * sin(t)) * u, (hcy - hry * kk * cos(t)) * u, z * u))
    path = Spline(*pts)
    tube = sweep(Plane(origin=path @ 0, z_dir=path % 0) * Circle(mr * u), path)
    rd = mr * u * 1.25
    tube += _ellipsoid(rd, rd, rd, *pts[0]) + _ellipsoid(rd, rd, rd, *pts[-1])
    frog -= tube
    frog = frog & _halfspace_above(0)
    sock = extrude(RectangleRounded(p.rod_a + 2 * L["sn"], p.rod_b + 2 * L["sn"], p.rod_corner_r + L["sn"]), p.socket_depth)
    frog -= Pos(0, 0, -0.01) * sock
    return frog


# ---------------------------------------------------------------- design
def _shapes(p, L):
    """Part geometry doesn't depend on crank_deg (only placements do). The motion sweep rebuilds
    the design at every pose, so cache the solids per (design source, params minus crank_deg)."""
    import hashlib
    import sys
    from pathlib import Path
    cache = sys.__dict__.setdefault("_forge_automaton_b_cache", {})
    key = hashlib.sha256(Path(__file__).read_bytes() + repr(sorted(
        (k, v) for k, v in vars(p).items() if k != "crank_deg")).encode()).hexdigest()
    if key not in cache:
        cache.clear()
        cache[key] = (make_base(p, L), make_crankshaft(p, L), make_camblock(p, L),
                      make_follower(p, L), make_frog(p, L))
    return cache[key]


def build(p) -> Design:
    L = _layout(p)
    a = p.crank_deg
    base, crank, cams, fol, frog = _shapes(p, L)

    frog_colors = ["#5DBB4A", "#7CCB3E", "#3FA34D"]
    parts = [
        Part("base", base, color="#2A9D8F", orient=(180, 0, 0), cosmetic=["+z", "-y", "+y", "-x", "+x"],
             notes="Pond box, printed deck-down on the textured plate; pads and ripples are engraved V-grooves."),
        Part("crankshaft", crank, color="#E76F51", placement=((0, 0, p.shaft_z), (a, 0, 0)), orient=(0, 0, 0),
             notes="Shaft, arm and knob in one piece; prints lying on the D-flat."),
        Part("camblock", cams, color="#F4A261", placement=((0, 0, p.shaft_z), (a, 0, 0)), orient=(0, -90, 0),
             notes="Three eccentrics at 120 deg on a D-bored hub; printed on its -X disc."),
    ]
    fits = [
        Fit("crankshaft", "base", "loose",
            region=Region((-p.base_w / 2 - 1, -p.crank_hub_r + 0.5, p.shaft_z - p.crank_hub_r + 0.5),
                          (p.base_w / 2 + p.hub_gap + 0.3, p.crank_hub_r - 0.5, p.shaft_z + p.crank_hub_r - 0.5)),
            notes="Both bearing holes and the hub-to-wall face."),
        Fit("camblock", "crankshaft", "snug", notes="D-flat key."),
    ]
    sleeve_lo = p.base_h - p.guide_len
    for i, (x, phi) in enumerate(zip(L["xs"], L["phis"])):
        zf = _foot_z(p, phi)
        fn, gn = f"follower_{i + 1}", f"frog_{i + 1}"
        parts.append(Part(fn, fol, color="#6A994E", placement=((x, 0, zf), (0, 0, 0)), orient=(0, 0, 0),
                          notes="Foot + keyed rod; the foot is the stop under the guide sleeve."))
        parts.append(Part(gn, frog, color=frog_colors[i], placement=((x, 0, zf + L["frog_dz"]), (0, 0, 0)),
                          orient=(0, 0, 0), cosmetic=["+z", "-y"], notes="Pressed onto the rod's keyed tip."))
        fits += [
            Fit("camblock", fn, "contact", notes="Flat foot on eccentric; 0.1 mm modelled gap."),
            Fit(fn, "base", "sliding",
                region=Region((x - p.foot_w / 2, -p.foot_d / 2, sleeve_lo + 0.2), (x + p.foot_w / 2, p.foot_d / 2, p.base_h - 0.2)),
                notes="Keyed rod in its guide sleeve."),
            Fit(gn, fn, "snug", notes="Keyed socket on the rod tip."),
        ]
    return Design(
        parts=parts, fits=fits,
        explode={"frog_1": (0, 0, 25), "frog_2": (0, 0, 25), "frog_3": (0, 0, 25),
                 "follower_1": (0, 0, 12), "follower_2": (0, 0, 12), "follower_3": (0, 0, 12),
                 "camblock": (0, 0, -30), "crankshaft": (30, 0, 0)},
        motion=Motion("crank_deg", 0, 360, 15, min_travel_mm=6, min_travel_deg=20,
                      exclude_travel=("crankshaft", "camblock")),
    )
