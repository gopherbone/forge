"""Frog Automaton A, "Fly Catcher". All dimensions come from spec.yaml `params` (p.*).

Assembly frame: desk at z=0, base centred on X/Y, the frog faces -Y (towards the fly),
the crank is on +X. Mechanism:

  crank -> D-flat shaft (along X) -> one eccentric cam -> flat-footed TONGUE follower that
  slides up-and-forward in an inclined bore through the frog body -> its rounded top pushes
  the flat palate of the HEAD, which pivots on a PIN through a tab at the back of the body.

Kinematics are closed-form, so every part is placed exactly from p.crank_deg:
  - eccentric centre c(theta) = Rx(theta) * e*u, where u is the follower axis
  - follower foot distance along u:  s = c.u + R + gap = e*cos(theta - phase) + R + gap
  - head angle a solves  A*sin(a) + B*cos(a) = K  (nub centre vs palate plane, see _head_angle)
crank_deg = phase is fully open (tongue out), phase + 180 is closed.

Print notes: base ring prints upright (open top and bottom, no ceilings); the body prints
on its deck plate; the head prints on its flat palate; cam, tongue and crank-shaft print on
flat faces; the shaft and pin carry a full-length D-flat so they can lie on the bed.
"""
from math import asin, atan2, cos, degrees, radians, sin, sqrt

from build123d import *

from forge.config import fits_table
from forge.dsl import Design, Fit, Motion, Part, Region


# ----------------------------------------------------------------- helpers
def _ell(rx, ry, rz, at=(0, 0, 0), trim=0.02):
    """Ellipsoid with both poles trimmed by `trim` mm: exposed sphere poles tessellate into
    degenerate, non-watertight fans."""
    e = scale(Sphere(1), by=(rx, ry, rz)) & Box(2 * rx + 2, 2 * ry + 2, 2 * rz - 2 * trim)
    return Pos(*at) * e


def _sph(r, at=(0, 0, 0)):
    return _ell(r, r, r, at)


def _dome(rx, ry, rz, at):
    """Upper half of an ellipsoid whose equator sits at `at` (no overhangs when printed on it)."""
    x, y, z = at
    return _ell(rx, ry, rz, at) & Pos(x, y, z + rz) * Box(2 * rx + 2, 2 * ry + 2, 2 * rz)


def _yz(face, t):
    """Extrude a 2D face drawn in (y, z) symmetrically along X by total thickness t."""
    return extrude(Plane.YZ * face, t / 2, both=True)


def _stadium(p1, p2, r):
    """2D slot between two centre points (in the sketch plane)."""
    (x1, y1), (x2, y2) = p1, p2
    dx, dy = x2 - x1, y2 - y1
    L = sqrt(dx * dx + dy * dy)
    f = Pos(x1, y1) * Circle(r) + Pos(x2, y2) * Circle(r)
    if L > 1e-6:
        nx, ny = -dy / L * r, dx / L * r
        f += Polygon((x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny), align=None)
    return f


def _sweep2d(p1, p2, r, d):
    """Minkowski sum of stadium(p1, p2, r) with the segment 0..d: the area a translating slot covers."""
    a, b = p1, p2
    a2, b2 = (a[0] + d[0], a[1] + d[1]), (b[0] + d[0], b[1] + d[1])
    f = _stadium(a, b, r) + _stadium(a2, b2, r) + _stadium(a, a2, r) + _stadium(b, b2, r)
    f += Polygon(a, b, b2, a2, align=None)
    return f


def _try(fn, shape, *a):
    try:
        out = fn(shape, *a)
        return out if out is not None and out.is_valid else shape
    except Exception:
        return shape


def _fillet(shape, r, edges):
    return _try(lambda s, rr, ee: s.fillet(rr, ee), shape, r, edges) if edges else shape


def _chamfer(shape, d, edges):
    return _try(lambda s, dd, ee: s.chamfer(dd, None, ee), shape, d, edges) if edges else shape


# ----------------------------------------------------------------- kinematics
def kinematics(p):
    fits = fits_table()
    snug = fits["snug"]["gap"]
    b = radians(p.rod_beta)
    u = (-sin(b), cos(b))                        # (y, z): follower axis, up and forward
    R = p.cam_e + p.shaft_d / 2 + snug + p.cam_wall
    s_min = R - p.cam_e + p.contact_gap
    th = radians(p.crank_deg - p.cam_phase)
    s = p.cam_e * cos(th) + R + p.contact_gap
    ds = s - s_min                               # follower lift along u from the closed pose
    z_p = p.base_h                               # deck top
    z_m = z_p + p.mouth_h                        # mouth floor (lower-jaw top)
    z_h = z_m + p.mouth_gap + p.hinge_c          # hinge axis
    y_h = p.hinge_y
    K = p.hinge_c + p.rod_w / 2 + p.contact_gap  # palate offset + nub radius + gap

    # nub centre N(L) = shaft + L*u. Choose L_rest so the head rests at rest_deg when closed:
    # A sin a + B cos a = K, A = (y_h - y_s) + L sin b, B = (z_h - z_s) - L cos b
    a0 = radians(p.rest_deg)
    L_rest = (K - (y_h - p.shaft_y) * sin(a0) - (z_h - p.shaft_z) * cos(a0)) / (-cos(a0 + b))

    def head_angle(L):
        A = (y_h - p.shaft_y) + L * sin(b)
        B = (z_h - p.shaft_z) - L * cos(b)
        rho = sqrt(A * A + B * B)
        return degrees(asin(K / rho) - atan2(B, A))

    return dict(u=u, R=R, s_min=s_min, s=s, ds=ds, z_p=z_p, z_m=z_m, z_h=z_h, y_h=y_h, K=K,
                L_rest=L_rest, alpha=head_angle(L_rest + ds), alpha_max=head_angle(L_rest + 2 * p.cam_e),
                alpha_min=head_angle(L_rest), snug=snug, loose=fits["loose"]["gap"],
                sliding=fits["sliding"]["gap"])


# ----------------------------------------------------------------- build
def build(p) -> Design:
    k = kinematics(p)
    u, R, z_p, z_m, z_h, y_h = k["u"], k["R"], k["z_p"], k["z_m"], k["z_h"], k["y_h"]
    snug, loose, slide = k["snug"], k["loose"], k["sliding"]
    ys, zs = p.shaft_y, p.shaft_z
    W, D, H, t = p.base_w, p.base_d, p.base_h, p.wall
    xi = W / 2 - t                                # inner face of the end walls
    z_pb = H - p.plate_t                          # deck plate underside = ledge top
    flat_z = -(p.shaft_d / 2 - p.dflat)           # shaft D-flat plane (shaft frame)

    # ============================ base: pond box (ring, open top and bottom)
    outer = extrude(RectangleRounded(W, D, p.corner_r), H)
    inner = extrude(RectangleRounded(W - 2 * t, D - 2 * t, p.corner_r - t), H + 2)
    base = outer - Pos(0, 0, -1) * inner
    base = _chamfer(base, p.edge_chamfer, base.edges().group_by(Axis.Z)[0].filter_by(
        lambda e: abs(e.center().X) > W / 2 - 0.5 or abs(e.center().Y) > D / 2 - 0.5))
    top_outer = [e for e in base.edges().group_by(Axis.Z)[-1]
                 if abs(e.center().X) > W / 2 - 0.5 or abs(e.center().Y) > D / 2 - 0.5
                 or (abs(e.center().X) > W / 2 - p.corner_r and abs(e.center().Y) > D / 2 - p.corner_r
                     and e.center().X ** 2 + e.center().Y ** 2 > (W / 2 - t) ** 2 + (D / 2 - t) ** 2 - 40)]
    base = _fillet(base, p.top_fillet, top_outer)
    # ledge for the deck plate, 45-degree underside (prints without support)
    lw = p.ledge_w
    ri = p.corner_r - t
    ov = p.ledge_key   # ledge block reaches into the wall; the 45-degree cut meets the wall face transversally
    lv = p.ledge_lip  # vertical inner face so the ledge has no knife edge
    zl = z_pb - lw - ov - lv
    ledge = Pos(0, 0, zl) * extrude(RectangleRounded(W - 2 * t + 2 * ov, D - 2 * t + 2 * ov, ri + ov), lw + ov + lv)
    inner_w, inner_d, inner_r = W - 2 * t - 2 * lw, D - 2 * t - 2 * lw, max(ri - lw, 0.5)
    ledge -= loft([Plane.XY.offset(zl - 0.01) * RectangleRounded(W - 2 * t + 2 * ov + 0.02, D - 2 * t + 2 * ov + 0.02, ri + ov + 0.01),
                   Plane.XY.offset(z_pb - lv) * RectangleRounded(inner_w, inner_d, inner_r)])
    ledge -= Pos(0, 0, z_pb - lv - 0.01) * extrude(RectangleRounded(inner_w, inner_d, inner_r), lv + 0.02)
    base += ledge
    # bearing bosses + bearing holes (loose fit)
    for sx in (1, -1):
        base += Pos(sx * (xi - p.boss_l / 2 + 0.01), ys, zs) * Rot(0, 90, 0) * Cylinder(p.boss_r, p.boss_l + 0.02)
    base -= Pos(0, ys, zs) * Rot(0, 90, 0) * Cylinder(p.shaft_d / 2 + loose, W + 10)
    # pond motif: proud lily pads on the long faces
    def lily(r, notch_deg):
        f = Circle(r)
        n = r * 1.3
        f -= Polygon((0, 0), (n * sin(radians(notch_deg / 2)), n * cos(radians(notch_deg / 2))),
                     (-n * sin(radians(notch_deg / 2)), n * cos(radians(notch_deg / 2))), align=None)
        return f
    front = Plane(origin=(0, -D / 2 + 0.01, 0), x_dir=(1, 0, 0), z_dir=(0, -1, 0))
    back = Plane(origin=(0, D / 2 - 0.01, 0), x_dir=(-1, 0, 0), z_dir=(0, 1, 0))
    # pads seen edge-on on the water: flattened ellipses with a narrow notch, so they read as
    # lily pads (round pads with a wedge read as letters on a vertical face)
    def pad_side(r):
        f = Ellipse(r, r * p.pad_squash)
        n = r * 1.3
        h = radians(p.pad_notch_deg)
        f -= Polygon((0, 0), (n * sin(h), n * cos(h)), (-n * sin(h), n * cos(h)), align=None)
        return f
    for pl, pads in ((front, p.pads_front), (back, p.pads_back)):
        for (x, z, r) in pads:
            pad = extrude(pl * (Pos(x, z) * pad_side(r)), p.relief)
            pad = _chamfer(pad, p.pad_chamfer, pad.edges().filter_by(
                lambda e, pl=pl: abs((e.center() - pl.origin).dot(pl.z_dir) - p.relief) < 0.05))
            base += pad

    # ============================ shaft with crank arm and knob (shaft frame: axis = X)
    xa0 = W / 2 + p.crank_gap
    xa1 = xa0 + p.arm_t
    kr = p.knob_d / 2
    zc = flat_z + p.knob_drop                     # arm/knob centre height: flat cut leaves a >=45 deg edge
    shaft = Pos((-W / 2 + xa1) / 2, 0, 0) * Rot(0, 90, 0) * Cylinder(p.shaft_d / 2, xa1 + W / 2)
    shaft = _chamfer(shaft, p.small_chamfer, shaft.edges().filter_by(lambda e: e.center().X < -W / 2 + 0.1))
    arm = Pos(xa0 + p.arm_t / 2, 0, 0) * _yz(_stadium((0, zc), (p.crank_r, zc), kr), p.arm_t)
    arm = _fillet(arm, p.arm_fillet, arm.edges().filter_by(lambda e: e.center().X > xa1 - 0.1))
    knob = Pos(xa1 + p.knob_l / 2 - 0.01, p.crank_r, zc) * Rot(0, 90, 0) * Cylinder(kr, p.knob_l + 0.02)
    knob = _fillet(knob, kr * 0.6, knob.edges().filter_by(lambda e: e.center().X > xa1 + p.knob_l - 0.2))
    shaft = shaft + arm + knob
    shaft -= Pos(0, 0, flat_z - 10) * Box(4 * W, 4 * W, 20)        # full-length D-flat (and print face)

    # ============================ cam: one eccentric + hub to the +X boss (cam frame = shaft frame)
    ec = (p.cam_e * u[0], p.cam_e * u[1])                          # eccentric centre at phase pose
    cam = Pos(0, *ec) * Rot(0, 90, 0) * Cylinder(R, p.cam_t)
    cam = _chamfer(cam, p.edge_chamfer, [e for e in cam.edges() if e.geom_type == GeomType.CIRCLE])
    hub_r = R - p.cam_e - p.hub_inset   # strictly inside the disc outline (no tangent seam)
    hub_x1 = xi - p.boss_l - p.cam_end_gap
    cam += Pos((p.cam_t / 2 + hub_x1) / 2 - 0.01, 0, 0) * Rot(0, 90, 0) * Cylinder(hub_r, hub_x1 - p.cam_t / 2 + 0.02)
    hr = p.shaft_d / 2 + snug
    dhole = Circle(hr) - Pos(0, flat_z - snug - 10) * Rectangle(20, 20)
    cam -= Pos(-W / 2, 0, 0) * extrude(Plane.YZ * dhole, W)

    # ============================ tongue follower (modelled in the assembly frame, closed pose)
    def at(L, dn=0.0):  # point on the follower: L along u from the shaft axis, dn sideways (back/up)
        return (ys + L * u[0] + dn * u[1], zs + L * u[1] - dn * u[0])
    hw = p.rod_w / 2
    Lf, Ln = k["s_min"], k["L_rest"]
    N = at(Ln)
    blade = Polygon(at(Lf, hw), at(Ln, hw), at(Ln, -hw), at(Lf, -hw), align=None) + Pos(*N) * Circle(hw)
    Np = (N[0] + p.neck_dy, N[1] + p.neck_dz)
    T = (N[0] + p.tip_dy, N[1] + p.tip_dz)
    tongue = _yz(blade + _stadium(Np, T, p.tip_r), p.rod_t)
    tongue = _fillet(tongue, p.tongue_fillet, tongue.edges().filter_by(lambda e: e.center().X > p.rod_t / 2 - 0.05))
    tongue = _chamfer(tongue, p.small_chamfer, tongue.edges().filter_by(lambda e: e.center().X < -p.rod_t / 2 + 0.05))

    # ============================ body: deck plate + lily pad + frog lower body + hinge tab + fly
    pg = slide
    body = Pos(0, 0, z_pb) * extrude(RectangleRounded(W - 2 * t - 2 * pg, D - 2 * t - 2 * pg, ri - pg), p.plate_t)
    body = _chamfer(body, p.edge_chamfer, body.edges().group_by(Axis.Z)[0])
    body = _fillet(body, p.lip_fillet, body.edges().group_by(Axis.Z)[-1])
    pad = Pos(0, p.pad_y, z_p - 0.01) * extrude(Rot(0, 0, 90) * lily(p.pad_r, p.deck_pad_notch_deg), p.relief + 0.01)
    body += _fillet(pad, p.pad_chamfer, pad.edges().group_by(Axis.Z)[-1])
    frog = _dome(p.body_rx, p.body_ry, p.body_rz, (0, p.body_y, z_p))
    for sx in (1, -1):
        frog += _dome(p.haunch_rx, p.haunch_ry, p.haunch_rz, (sx * p.haunch_x, p.haunch_y, z_p))
        frog += _dome(p.foot_rx, p.foot_ry, p.foot_rz, (sx * p.foot_x, p.foot_y, z_p))
    frog &= Pos(0, 0, z_m - 50) * Box(200, 200, 100)              # flat mouth floor
    frog = _fillet(frog, p.lip_fillet, [e for e in frog.edges() if abs(e.center().Z - z_m) < 0.01 and e.length > 40])
    body += frog
    tab = Pos(0, y_h, z_h) * Rot(0, 90, 0) * Cylinder(p.tab_r, p.tab_t)
    tab += Pos(0, y_h, (z_m - p.tab_root + z_h) / 2) * Box(p.tab_t, 2 * p.tab_r, z_h - z_m + p.tab_root)
    tab -= Pos(0, y_h, z_h) * Rot(0, 90, 0) * Cylinder(p.pin_d / 2 + loose, p.tab_t + 2)
    body += tab
    # the fly on its stalk
    fz = z_m + p.fly_dz
    body += Pos(0, p.fly_y, (z_p + fz) / 2) * Cylinder(p.stalk_d / 2, fz - z_p)
    fly = Pos(0, p.fly_y, fz) * _sph(p.fly_r)
    fly += Pos(0, p.fly_y, fz - p.fly_r * 1.41) * Cone(0, p.fly_r * 0.71, p.fly_r * 0.71, align=(Align.CENTER, Align.CENTER, Align.MIN))
    for sx in (1, -1):
        wing = _ell(p.fly_r * 1.1, p.fly_r * 0.6, p.wing_t / 2, (0, 0, 0))
        fly += Pos(sx * p.fly_r * 0.9, p.fly_y + 0.6, fz + p.fly_r * 0.7) * Rot(0, sx * -35, 0) * wing
    body += fly
    # follower bore (sliding fit) and the space the tongue tip sweeps through
    travel = 2 * p.cam_e
    d = (travel * u[0], travel * u[1])
    bw = hw + slide
    bore = Polygon(at(Lf - 20, bw), at(Ln + travel + 10, bw), at(Ln + travel + 10, -bw), at(Lf - 20, -bw), align=None)
    body -= _yz(bore, p.rod_t + 2 * slide)
    gg = p.groove_gap
    body -= _yz(_sweep2d(Np, T, p.tip_r + gg, d) + _sweep2d(N, N, hw + gg, d), p.rod_t + 2 * gg)
    # clean notch in the lower lip in front of the resting tongue tip (no slivers where the sweep grazes the lip)
    nz0 = T[1] - p.tip_r - gg
    y_lip = p.body_y - p.body_ry * sqrt(max(0.0, 1 - ((nz0 - z_p) / p.body_rz) ** 2)) - p.notch_margin   # just past the chin
    body -= Pos(0, (T[0] + y_lip) / 2, (nz0 + z_m + 5) / 2) * Box(p.rod_t + 2 * gg, T[0] - y_lip, z_m + 5 - nz0)

    # ============================ head (head frame: origin on the hinge axis, palate at z = -c)
    c = p.hinge_c
    hy = p.head_y - y_h
    head = _dome(p.head_rx, p.head_ry, p.head_rz, (0, hy, -c))
    hinge_core = head & (Rot(0, 90, 0) * Cylinder(c, 4 * p.head_rx))
    gam = radians(k["alpha_max"] + p.rear_clear_deg)
    rear = Polygon((0, -c - 1), (0, 0), (40, 40 * sin(gam) / cos(gam)), (40, -c - 1), align=None)
    head -= _yz(rear, 4 * p.head_rx)                              # head behind the hinge stays above the axis
    head += hinge_core
    for sx in (1, -1):
        ex, ey = sx * p.eye_x, p.eye_y - y_h
        zs_ = p.head_rz * sqrt(max(0.0, 1 - (p.eye_x / p.head_rx) ** 2 - ((p.eye_y - p.head_y) / p.head_ry) ** 2)) - c
        ez = zs_ + p.eye_lift
        er = p.eye_r
        eye = Pos(ex, ey, ez) * _sph(er)
        eye += Pos(ex, ey, ez - er * 1.414) * Cone(0, er * 0.707, er * 0.707, align=(Align.CENTER, Align.CENTER, Align.MIN))
        head += eye
        # pupil: a dimple looking forward and a little outward
        dx, dy, dz = sx * 0.35, -1.0, 0.45
        nrm = sqrt(dx * dx + dy * dy + dz * dz)
        off = er + p.pupil_r - p.pupil_depth
        head -= Pos(ex + off * dx / nrm, ey + off * dy / nrm, ez + off * dz / nrm) * _sph(p.pupil_r)
        # nostril
        ny_ = p.head_y - p.head_ry * 0.86 - y_h
        nz_ = p.head_rz * sqrt(max(0.0, 1 - (p.nostril_x / p.head_rx) ** 2 - 0.86 ** 2)) - c
        head -= Pos(sx * p.nostril_x, ny_, nz_) * _sph(p.nostril_r)
    # slot for the body's hinge tab (the tab is fixed; the head swings round it)
    sr = p.tab_r + p.slot_gap
    sxw = p.tab_t + 2 * p.slot_gap
    head -= Rot(0, 90, 0) * Cylinder(sr, sxw)
    head -= Pos(0, (-sr + sr + p.slot_back) / 2, -c / 2 - 0.5) * Box(sxw, sr + sr + p.slot_back, c + 1)
    # pin hole (snug: the pin turns with the head) and tympanum spot faces
    head -= Rot(0, 90, 0) * Cylinder(p.pin_d / 2 + snug, 4 * p.head_rx)
    for sx in (1, -1):
        head -= Pos(sx * (p.pin_l / 2 + 10), 0, 0) * Rot(0, 90, 0) * Cylinder(p.tymp_r, 20)
    head = _chamfer(head, p.head_lip_chamfer, head.edges().filter_by(lambda e: abs(e.center().Z + c) < 0.01
                                                                          and e.length > 20))

    # ============================ pin (head frame)
    pin = Rot(0, 90, 0) * Cylinder(p.pin_d / 2, p.pin_l)
    pin = _chamfer(pin, p.pin_chamfer, pin.edges().filter_by(lambda e: abs(abs(e.center().X) - p.pin_l / 2) < 0.05))
    pin -= Pos(0, 0, -(p.pin_d / 2 - p.pin_flat) - 5) * Box(p.pin_l + 2, 10, 10)

    # ============================ placements from crank_deg
    th = p.crank_deg
    ds = k["ds"]
    rot_shaft = ((0, ys, zs), (th, 0, 0))
    head_pl = ((0, y_h, z_h), (-k["alpha"], 0, 0))
    tongue_pl = ((0, ds * u[0], ds * u[1]), (0, 0, 0))

    parts = [
        Part("base", base, color="#3b82b0", orient=(0, 0, 0), cosmetic=["-y", "+y", "-x"],
             notes="Pond box: a ring, open top and bottom, so nothing inside needs support. Shaft bearings with bosses."),
        Part("body", body, color="#4f9d3a", orient=(0, 0, 0), cosmetic=["+z", "-y"],
             notes="Deck plate + lily pad + frog lower body + hinge tab + fly. Drops onto the base ledge."),
        Part("head", head, color="#7cc142", placement=head_pl, orient=(0, 0, 0), cosmetic=["+z", "-y"],
             notes="Upper jaw with eyes. Prints on its flat palate. Gravity keeps it on the tongue."),
        Part("pin", pin, color="#7cc142", placement=head_pl, orient=(0, 0, 0),
             notes="Hinge pin: snug in the head, loose in the body tab. D-flat to print lying down."),
        Part("tongue", tongue, color="#e8607f", placement=tongue_pl, orient=(0, -90, 0),
             notes="Flat-footed cam follower. Its round top is the tongue and pushes the head open."),
        Part("cam", cam, color="#f2b134", placement=rot_shaft, orient=(0, -90, 0),
             notes="Eccentric with a hub that stops the shaft pulling out at the +X boss. D-bore, snug."),
        Part("shaft", shaft, color="#8a5a35", placement=rot_shaft, orient=(0, 0, 0), cosmetic=["+x"],
             notes="Camshaft, crank arm and knob in one, sharing one D-flat plane so it prints lying down."),
    ]

    # ============================ fits (regions in the assembly frame at the spec pose)
    br = p.boss_r + 1
    fits = [
        Fit("shaft", "base", "loose", region=Region((-W / 2 - 1, ys - br, zs - br), (W / 2 + 0.1, ys + br, zs + br)),
            notes="Shaft in the two bearing holes. The crank arm sits crank_gap outside the +X wall."),
        Fit("cam", "shaft", "snug", notes="D-flat bore."),
        Fit("tongue", "cam", "contact", notes=f"Flat foot rides the eccentric with a {p.contact_gap} mm running gap at every angle."),
        Fit("tongue", "body", "sliding", region=Region((-5, -30, z_pb + 0.2), (5, 30, z_m - 1.5)),
            notes="Follower in its inclined bore through the deck plate and body."),
        Fit("head", "tongue", "contact", notes=f"Tongue top pushes the flat palate; {p.contact_gap} mm running gap."),
        Fit("head", "pin", "snug", region=Region((-p.pin_l / 2, y_h - 3, z_h - 3), (p.pin_l / 2, y_h + 3, z_h + 3))),
        Fit("pin", "body", "loose", region=Region((-p.tab_t / 2 - 0.5, y_h - 4, z_h - 4), (p.tab_t / 2 + 0.5, y_h + 4, z_h + 4)),
            notes="Head pivot: the pin turns in the body tab."),
        Fit("base", "body", "contact", notes="Deck plate rests on the ledge, sliding clearance to the walls."),
    ]
    return Design(
        parts=parts, fits=fits,
        motion=Motion("crank_deg", 0, 360, 15, min_travel_mm=6, min_travel_deg=20, exclude_travel=("shaft", "cam")),
        explode={"base": (0, 0, 0), "body": (0, 0, 25), "head": (0, 0, 45), "pin": (0, 0, 45),
                 "tongue": (0, 0, 12), "cam": (0, 0, -20), "shaft": (25, 0, -20)},
    )
