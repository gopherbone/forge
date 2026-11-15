"""Frog Automaton: "Leapfrog Pond + Fly Catcher" (merged B + A), detail design.

Three frogs in a row on a pond. Turning the side crank turns one camshaft:
  - the two outer frogs hop (eccentric cams 180 deg apart, flat-footed keyed followers),
  - the middle frog's tongue (an inclined follower) rises out of its mouth and pushes the
    hinged head open (A's mechanism),
  - a fly on its own cam bobs up just after the tongue arrives, so it always gets away.

Parts and print orientation (every wall meets the plate vertically; nothing rounds off the bed):
  base        ring: open top and bottom, printed upright. Bearing holes have a 90-deg round
              bottom arc (the shaft runs on it) and a 45-deg roof. Waterline band + reeds outside.
  deck        flat pond plate printed top-up: raised lily pads (frog guides), an inclined sleeve
              for the tongue (the middle frog is pressed onto it), two in-plane snap fingers.
  crankshaft  shaft + hub + leaf arm + knob, printed lying on one flat. Triple-flat section:
              vertical side flats in the bottom 2 mm, so nothing curls off the plate.
  clip        lily-pad C-ring that snaps radially onto a keyed neck at the -X end (retention).
  camblock    four eccentrics on one hub, printed on end (round, true bores).
  follower_1/3, frog_1/3   hoppers: frog pressed on the rod tip over crush ribs.
  body, head, pin, tongue  middle frog: body pressed on the deck sleeve, head hinged on a
              press-fit pin, the tongue follower pushes the head's palate.
  fly         follower with an L-plate foot, a stalk and the fly.

Frames: desk z=0, base centred in x/y, frogs face -Y, crank on +X. "Shaft frame" = x along the
shaft axis, origin on the axis, part flat at z = -shaft_zf.
Every dimension is a p.<param>; FROG holds dimensionless proportions for the hopper frogs.
"""
from math import asin, atan2, cos, degrees, radians, sin, sqrt, tan

from build123d import *

from forge.config import fits_table
from forge.dsl import Design, Fit, LoadCase, Motion, Part, Region

POLE_TRIM = 0.02



# ---------------------------------------------------------------- helpers
def _ell(rx, ry, rz, at=(0, 0, 0)):
    e = scale(Sphere(1), by=(rx, ry, rz)) & Box(2 * rx + 2, 2 * ry + 2, 2 * (rz - POLE_TRIM))
    return Pos(*at) * e


def _dome(rx, ry, rz, at):
    """Upper half of an ellipsoid with its equator at `at`: vertical where it meets the plane."""
    x, y, z = at
    return _ell(rx, ry, rz, at) & Pos(x, y, z + rz) * Box(2 * rx + 2, 2 * ry + 2, 2 * rz)


def _above(z, big=400):
    return Pos(0, 0, z + big / 2) * Box(big, big, big)


def _xprism(face, x0, x1):
    """Extrude a sketch drawn in (y, z) along +X from x0 to x1."""
    return extrude(Plane.YZ.offset(x0) * face, x1 - x0, dir=(1, 0, 0))


def _yzsym(face, t):
    """Extrude a (y, z) sketch symmetrically along X, total thickness t. Each face is extruded on its own and the
    pieces are fused in 3D (2D unions of overlapping sketches stay split and make bad boolean tools)."""
    faces = face.faces() if hasattr(face, "faces") else [face]
    out = None
    for f in faces:
        e = extrude(Plane.YZ * f, t / 2, dir=(1, 0, 0), both=True)
        out = e if out is None else out + e
    return out


def _tri_flat(r, zf, cy=0.0, cz=0.0):
    """(y, z) section of a round printed lying down: circle(r) at (cy, cz), cut by the bed plane
    z = -zf and by vertical side flats where the circle meets that plane. Every wall in the bottom
    2 mm is vertical (needs cz + zf >= 1)."""
    d = cz + zf
    a = sqrt(max(r * r - d * d, 0.01))
    top = cz + r + 1
    return (Pos(cy, cz) * Circle(r)) & (Pos(cy, (top - zf) / 2) * Rectangle(2 * a, top + zf))


def _tri_flat_off(r, zf, off):
    """_tri_flat(r, zf) grown by `off` on every face (a true constant-clearance bore)."""
    a = sqrt(r * r - zf * zf) + off
    top = r + off + 1
    return Circle(r + off) & (Pos(0, (top - zf - off) / 2) * Rectangle(2 * a, top + zf + off))


def _quad_flat(r, zf, off=0.0):
    """Rounded-square section of a round printed lying down: circle(r) cut by flats at z = +-zf and
    y = +-sqrt(r^2 - zf^2) (vertical walls at the bed, flat on top), grown by `off` on every face."""
    a = sqrt(r * r - zf * zf) + off
    return Circle(r + off) & Rectangle(2 * a, 2 * (zf + off))


def _tangent_pt(r, a1, a2):
    """Intersection of the tangents to circle(r) at polar angles a1, a2 (deg)."""
    n1 = (cos(radians(a1)), sin(radians(a1)))
    n2 = (cos(radians(a2)), sin(radians(a2)))
    k = r / (1 + n1[0] * n2[0] + n1[1] * n2[1])
    return ((n1[0] + n2[0]) * k, (n1[1] + n2[1]) * k)


def _bearing_hole(rh, cy=0.0, cz=0.0, arc_half=45.0):
    """Horizontal bearing/pivot hole in (y, z): a round bottom arc of 2*arc_half deg (< 180, the part
    that carries the shaft), tangent flanks, and a 45-deg roof. No drooping crown; the circle of
    radius rh is inscribed, so the clearance to a round of r is exactly rh - r everywhere."""
    lo, hi = 270 - arc_half, 270 + arc_half
    P = lambda a: Vector(rh * cos(radians(a)), rh * sin(radians(a)), 0)
    pts = [P(hi), Vector(*_tangent_pt(rh, 45, hi), 0), Vector(*_tangent_pt(rh, 135, 45), 0),
           Vector(*_tangent_pt(rh, lo, 135), 0), P(lo)]
    edges = [Edge.make_three_point_arc(P(lo), P(270), P(hi))]
    edges += [Edge.make_line(pts[k], pts[k + 1]) for k in range(4)]
    return Pos(cy, cz) * Face(Wire(edges))


def _stadium(p1, p2, r):
    (x1, y1), (x2, y2) = p1, p2
    dx, dy = x2 - x1, y2 - y1
    L = sqrt(dx * dx + dy * dy)
    f = Pos(x1, y1) * Circle(r) + Pos(x2, y2) * Circle(r)
    if L > 1e-6:
        nx, ny = -dy / L * r, dx / L * r
        f += Polygon((x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny), align=None)
    return f


def _hull_face(circles, n=48):
    """Single clean face: the convex hull of circles [(centre, r), ...] in the sketch plane."""
    import numpy as np
    from scipy.spatial import ConvexHull
    pts = np.array([(c[0] + r * cos(2 * 3.14159265 * k / n), c[1] + r * sin(2 * 3.14159265 * k / n))
                    for c, r in circles for k in range(n)])
    h = ConvexHull(pts)
    return Polygon(*[tuple(pts[i]) for i in h.vertices], align=None)


def _swept_stadium(p1, p2, r, d):
    """Area swept by stadium(p1, p2, r) translated by d: the hull of its four end circles."""
    q1, q2 = (p1[0] + d[0], p1[1] + d[1]), (p2[0] + d[0], p2[1] + d[1])
    return _hull_face([(p1, r), (p2, r), (q1, r), (q2, r)])


def _sweep2d(p1, p2, r, d):
    a, b = p1, p2
    a2, b2 = (a[0] + d[0], a[1] + d[1]), (b[0] + d[0], b[1] + d[1])
    f = _stadium(a, b, r) + _stadium(a2, b2, r) + _stadium(a, a2, r) + _stadium(b, b2, r)
    f += Polygon(a, b, b2, a2, align=None)
    return f


def _try(fn, shape):
    try:
        out = fn(shape)
        ok = out is not None and out.is_valid and abs(out.volume - shape.volume) < 0.05 * shape.volume
        return out if ok else shape
    except Exception:
        return shape


def _fillet(shape, r, edges):
    return _try(lambda s: s.fillet(r, edges), shape) if edges else shape


def _chamfer(shape, d, edges):
    return _try(lambda s: s.chamfer(d, None, edges), shape) if edges else shape


def _plinth(part, z):
    """Vertical-walled plinth: the cross-section of `part` at height z extruded down to z=0."""
    sl = part & Pos(0, 0, z + 0.0005) * Box(400, 400, 0.001)
    fs = [f for f in sl.faces() if abs(f.center().Z - z) < 1e-3 and f.normal_at().Z < -0.99]
    out = None
    for f in fs:
        e = extrude(f, amount=z, dir=(0, 0, -1))
        out = e if out is None else out + e
    return out


# ---------------------------------------------------------------- layout
def _layout(p):
    ft = fits_table()
    sn, sl, lo = ft["snug"]["gap"], ft["sliding"]["gap"], ft["loose"]["gap"]
    L = dict(sn=sn, sl=sl, lo=lo)
    L["xs"] = [-p.frog_pitch, 0.0, p.frog_pitch]
    L["x_in"] = p.base_w / 2 - p.wall
    L["y_in"] = p.base_d / 2 - p.wall
    L["x_rib"] = L["x_in"] - p.rib_t
    L["ys"] = p.shaft_y
    # vertical stack: hopper foot at its top + stop gap = deck underside
    L["zf_min"] = p.shaft_z - p.cam_e + p.cam_r + p.cam_follow_gap
    zf_max = p.shaft_z + p.cam_e + p.cam_r + p.cam_follow_gap
    L["deck_bot"] = zf_max + p.foot_t + p.stop_gap
    L["deck_top"] = L["deck_bot"] + p.deck_t
    L["pad_top"] = L["deck_top"] + p.pad_h
    L["ring_top"] = L["deck_top"] + p.rim_h
    L["frog_dz"] = L["pad_top"] + p.belly_gap - L["zf_min"]          # frog belly above the foot bottom
    L["rod_top"] = L["frog_dz"] + p.socket_depth - sn
    # tongue (inclined follower): axis through the shaft axis, tilted beta towards -Y
    b = radians(p.tongue_beta)
    L["u"] = (-sin(b), cos(b))
    L["v"] = (cos(b), sin(b))
    L["R_t"] = p.cam_r
    L["s_min"] = p.cam_r - p.cam_e + p.cam_follow_gap
    # phases: frog_1 peaks at crank 0, tongue at 90, fly at 90 + lag, frog_3 at 180
    # the fly's plate rides the tongue cam beside the tongue foot: as a vertical follower on that cam it
    # peaks 20 deg (= tongue_beta) before the tongue, so it is already rising when the tongue arrives
    L["phi"] = {"frog_1": 90.0, "tongue": p.tongue_beta, "fly": p.tongue_beta, "frog_3": -90.0}
    L["cam_x"] = {"frog_1": L["xs"][0], "tongue": 0.0, "frog_3": L["xs"][2]}
    L["fly_x0"] = p.tongue_t / 2 + 0.6                     # fly plate x-range on the tongue cam
    L["fly_x1"] = L["fly_x0"] + p.fly_cam_w
    # middle frog
    L["yb"] = p.shaft_y + p.body_dy
    L["z_p"] = L["pad_top"]
    L["z_m"] = L["z_p"] + p.mouth_h
    L["y_h"] = L["yb"] + p.hinge_dy
    L["z_h"] = L["z_m"] + p.mouth_gap + p.hinge_c
    L["K"] = p.hinge_c + p.tongue_w / 2 + p.cam_follow_gap
    a0 = radians(p.rest_deg)
    ys, zs = p.shaft_y, p.shaft_z
    L["L_rest"] = (L["K"] - (L["y_h"] - ys) * sin(a0) - (L["z_h"] - zs) * cos(a0)) / (-cos(a0 + b))
    return L


def _at(p, L, l, dn=0.0):
    """Point on the tongue follower: l along u from the shaft axis, dn along v (back/up)."""
    u, v = L["u"], L["v"]
    return (p.shaft_y + l * u[0] + dn * v[0], p.shaft_z + l * u[1] + dn * v[1])


def _foot_z(p, L, name):
    return p.shaft_z + p.cam_e * sin(radians(L["phi"][name] + p.crank_deg)) + p.cam_r + p.cam_follow_gap


def _tongue_ds(p, L):
    """Tongue lift along u from its lowest pose."""
    s = p.cam_e * cos(radians(L["phi"]["tongue"] + p.crank_deg - 90 - p.tongue_beta)) + p.cam_r + p.cam_follow_gap
    return s - L["s_min"]


def _head_angle(p, L, ds):
    b = radians(p.tongue_beta)
    l = L["L_rest"] + ds
    A = (L["y_h"] - p.shaft_y) + l * sin(b)
    B = (L["z_h"] - p.shaft_z) - l * cos(b)
    rho = sqrt(A * A + B * B)
    return degrees(asin(L["K"] / rho) - atan2(B, A))


# ---------------------------------------------------------------- base (ring)
def make_base(p, L):
    W, D, H = p.base_w, p.base_d, L["ring_top"]
    t = p.wall
    ri = p.corner_r - t
    base = extrude(RectangleRounded(W, D, p.corner_r), H) - Pos(0, 0, -1) * extrude(
        RectangleRounded(W - 2 * t, D - 2 * t, ri), H + 2)
    top = base.edges().group_by(Axis.Z)[-1]
    outer = [e for e in top if abs(e.center().X) > W / 2 - 0.3 or abs(e.center().Y) > D / 2 - 0.3
             or e.center().X ** 2 + e.center().Y ** 2 > (W / 2 - 1) ** 2 + (D / 2 - 1) ** 2 - 60]
    inner = [e for e in top if e not in outer]
    if p.rim_fillet > 0:
        base = _chamfer(base, p.rim_fillet, base.edges().group_by(Axis.Z)[-1].filter_by(
            lambda e: abs(e.center().X) > W / 2 - 0.3 or abs(e.center().Y) > D / 2 - 0.3
        or e.center().X ** 2 + e.center().Y ** 2 > (W / 2 - 1) ** 2 + (D / 2 - 1) ** 2 - 60))
    # bearing ribs (full height from the bed: no overhang), bearing holes
    rib_top = p.shaft_z + p.rib_above
    for s in (-1, 1):
        base += Pos(s * (L["x_in"] - p.rib_t / 2 + 0.05), L["ys"], rib_top / 2) * Box(p.rib_t + 0.1, p.rib_w, rib_top)
    hole = _xprism(_bearing_hole(p.shaft_r + L["lo"], L["ys"], p.shaft_z), -W / 2 - 1, W / 2 + 1)
    base -= hole
    # ledge for the deck: 45-deg underside
    zl = L["deck_bot"]
    lw = p.ledge_w
    ring_in = RectangleRounded(W - 2 * t + 0.02, D - 2 * t + 0.02, ri + 0.01)
    land = 0.8
    inner_off = RectangleRounded(W - 2 * t - 2 * lw, D - 2 * t - 2 * lw, max(ri - lw, 0.5))
    ledge = Pos(0, 0, zl - lw - land) * extrude(ring_in, lw + land)
    ledge -= extrude(Plane.XY.offset(zl - lw - land - 0.001) * RectangleRounded(W - 2 * t + 0.04, D - 2 * t + 0.04, ri + 0.02),
                     lw + 0.02, taper=45)
    ledge -= Pos(0, 0, zl - land - 0.01) * extrude(inner_off, land + 0.02)
    base += ledge
    # pockets: two front snap-finger lips (x < 0 and x > 0) and two rigid back tabs
    pd = p.lip_p - p.deck_gap + 0.3
    for k, (xc, sy) in enumerate(_lip_spots(p)):
        base -= Pos(xc, sy * (L["y_in"] + pd / 2 - 0.01), zl + (p.lip_h + p.lip_clear) / 2 - 0.01) * Box(
            p.lip_len + 0.8, pd + 0.02, p.lip_h + p.lip_clear + 0.02)
        if k < 2:   # back snap fingers: local 45-deg lead-in in the rim cams the lips inward as the deck goes down
            yw = sy * L["y_in"]
            ramp = Polygon((yw, H + 0.01), (yw + sy * p.rim_lead, H + 0.01), (yw, H - p.rim_lead), align=None)
            base -= _xprism(ramp, xc - p.lip_len / 2 - 0.6, xc + p.lip_len / 2 + 0.6)
    return base


def _lip_spots(p):
    """(x centre, y side) of the deck's lips: two snap fingers at the back, two rigid tabs at the front."""
    x_tip = p.fing_root_x + p.fing_l
    xl = x_tip - 1.2 - p.lip_len / 2              # back lips are inset 1.2 from the finger tip
    return [(-xl, 1), (xl, 1), (-p.tab_x, -1), (p.tab_x, -1)]


# ---------------------------------------------------------------- deck
def _lily(rx, ry, notch_deg, half_deg, r0):
    """Lily pad: ellipse with an open wedge notch starting at r0 from the centre."""
    f = Ellipse(rx, ry)
    a, h, R = radians(notch_deg), radians(half_deg), 3 * max(rx, ry)
    f -= Polygon((r0 * cos(a - h), r0 * sin(a - h)), (R * cos(a - h), R * sin(a - h)),
                 (R * cos(a + h), R * sin(a + h)), (r0 * cos(a + h), r0 * sin(a + h)), align=None)
    return f


def _tongue_prism(p, L, l0, l1, hw, ht):
    """Prism along the tongue axis: l0..l1 along u, +-hw along v, +-ht along X."""
    pts = [_at(p, L, l0, -hw), _at(p, L, l1, -hw), _at(p, L, l1, hw), _at(p, L, l0, hw)]
    return _yzsym(Polygon(*pts, align=None), 2 * ht)


def _vertical_entry(p, L, z0, h, hw, ht):
    """Vertical-walled box containing the inclined prism (+-hw along v, +-ht in X) between z0 and z0+h,
    so the bottom 2 mm of an inclined hole has vertical walls at the plate."""
    b = radians(p.tongue_beta)
    yc = lambda z: p.shaft_y - (z - p.shaft_z) * tan(b)
    y0, y1 = yc(z0 + h) - hw / cos(b), yc(z0) + hw / cos(b)
    box = Pos(0, (y0 + y1) / 2, z0 + h / 2) * Box(2 * ht, y1 - y0, h)
    roof = extrude(Plane.XY.offset(z0 + h - 0.01) * Pos(0, (y0 + y1) / 2) * Rectangle(2 * ht, y1 - y0), 3, taper=45)
    return box + roof


def _l_at_z(p, L, z):
    return (z - p.shaft_z) / L["u"][1]


def make_deck(p, L):
    """Pond surface, printed top-up: raised lily pads, the middle frog's body moulded on, two snap fingers
    at the back (they bend in the deck plane: in-layer), two rigid tabs at the front."""
    sl = L["sl"]
    zb, zt = L["deck_bot"], L["deck_top"]
    ye = L["y_in"] - p.deck_gap
    xe = L["x_in"] - p.deck_gap
    deck = Pos(0, 0, zb) * extrude(RectangleRounded(2 * xe, 2 * ye, p.corner_r - p.wall - p.deck_gap), p.deck_t)
    clipper = Pos(0, 0, zb) * extrude(RectangleRounded(2 * xe - 1.6, 2 * ye - 1.6, max(p.corner_r - p.wall - 1.0, 0.5)), 10)
    ys = L["ys"]

    def raised(face2d, at, h=p.pad_h):
        pad = Pos(at[0], at[1], zt - 0.01) * extrude(face2d, h + 0.01)
        return pad & clipper

    r0 = sqrt((p.rod_a / 2 + sl) ** 2 + (p.rod_b / 2 + sl) ** 2) + 1.6
    for x in (L["xs"][0], L["xs"][2]):
        deck += raised(_lily(p.pad_rx, p.pad_ry, -120 if x < 0 else -60, p.pad_notch_deg, r0), (x, ys))
    deck += raised(_lily(p.mid_pad_r, p.mid_pad_r, -35, p.pad_notch_deg, p.body_rx - 1.0), (0, L["yb"]))
    fx, fy = L["fly_x0"] + p.fly_t / 2, ys + p.fly_rod_dy
    deck += raised(Circle(p.fly_pad_r), (fx, fy), p.pad_h * 0.5)
    deck += make_sleeve(p, L)
    # holes: hopper guides, fly guide, inclined tongue guide (vertical-walled entry at the plate)
    rw, rh = p.relief_w, p.relief_h
    for x in (L["xs"][0], L["xs"][2]):
        deck -= Pos(x, ys, zb - 1) * extrude(RectangleRounded(p.rod_a + 2 * sl, p.rod_b + 2 * sl, p.rod_corner_r + sl), 20)
        deck -= Pos(x, ys, zb - 1) * extrude(RectangleRounded(p.rod_a + 2 * sl + 2 * rw, p.rod_b + 2 * sl + 2 * rw, p.rod_corner_r + sl + rw), 1 + rh)
    deck -= Pos(fx, fy, zb - 1) * extrude(Rectangle(p.fly_t + 2 * sl, p.rod_b + 2 * sl), 20)
    deck -= Pos(fx, fy, zb - 1) * extrude(Rectangle(p.fly_t + 2 * sl + 2 * rw, p.rod_b + 2 * sl + 2 * rw), 1 + rh)
    l_top = _l_at_z(p, L, L["z_p"]) + p.body_sock_d + 2
    deck -= _tongue_prism(p, L, _l_at_z(p, L, zb - 3), l_top, p.tongue_w / 2 + sl, p.tongue_t / 2 + sl)
    deck -= _vertical_entry(p, L, zb - 0.01, 2.21, p.tongue_w / 2 + sl, p.tongue_t / 2 + sl)
    # snap fingers at the back edge (left one drawn, mirrored), rigid tabs at the front
    xr, xt = -p.fing_root_x, -(p.fing_root_x + p.fing_l)
    y0, sw, ft = ye, p.fing_slot, p.fing_t
    cut = Pos((xt - sw + xr) / 2, y0 - ft - sw / 2) * Rectangle(xr - xt + sw, sw)
    cut += Pos(xr, y0 - ft - sw / 2) * Circle(p.fing_key_r)          # keyhole root: a full round, no sharp notch
    cut += Pos(xt - sw / 2, y0 - (ft + sw - 1) / 2) * Rectangle(sw, ft + sw + 1)
    cut += Polygon((xt - sw - 1.2, y0 + 0.01), (xt + 1.2, y0 + 0.01), (xt, y0 - 1.2), (xt - sw, y0 - 1.2), align=None)
    cut += Polygon((xt - 0.01, y0 - ft - 0.01), (xt + 1.0, y0 - ft - 0.01), (xt - 0.01, y0 - ft + 1.0), align=None)
    cut3 = Pos(0, 0, zb - 1) * extrude(cut, p.deck_t + 2)
    lip = Pos(xt + 1.2 + p.lip_len / 2, y0 + p.lip_p / 2 - 0.01, zb + p.lip_h / 2) * Box(p.lip_len, p.lip_p + 0.02, p.lip_h)
    for m in (False, True):
        deck -= mirror(cut3, about=Plane.YZ) if m else cut3
        deck += mirror(lip, about=Plane.YZ) if m else lip
    for sx in (-1, 1):
        deck += Pos(sx * p.tab_x, -y0 - p.lip_p / 2 + 0.01, zb + p.lip_h / 2) * Box(p.lip_len, p.lip_p + 0.02, p.lip_h)
    return deck


# ---------------------------------------------------------------- crankshaft, clip, camblock
def _clip_x(p):
    x_ci = -p.base_w / 2 - p.clip_gap                       # clip's wall-side face
    x_n0 = x_ci - p.tooth_t - 0.2                            # neck start (end-piece shoulder)
    return x_ci, x_n0


def make_crankshaft(p, L):
    """Shaft + arm + knob, printed lying on the shared flat. Simple and crisp: the shaft is a rounded square
    (flats top, bottom and sides, round corners on the bearing circle), the arm a straight flat-topped bar,
    the knob a flat-topped bar with a stadium end. Plan corners are rounded with vertical walls."""
    r, zf = p.shaft_r, p.shaft_zf
    W = p.base_w
    x_ci, x_n0 = _clip_x(p)
    xh = W / 2 + p.hub_gap
    xa = xh + p.crank_t
    sec = _quad_flat(r, zf)
    a_s = sqrt(r * r - zf * zf)
    shaft = _xprism(sec, -W / 2, xh + 0.5)
    shaft += _xprism(Pos(0, (p.neck_top - zf) / 2) * Rectangle(2 * p.neck_a, p.neck_top + zf), x_n0 - 0.01, -W / 2 + 0.01)
    endp = _xprism(sec, x_ci - p.clip_t + 0.1, x_n0)        # end piece: the shoulder the clip catches
    endp &= Pos((x_ci - p.clip_t + 0.1 + x_n0) / 2 - 0.5, 0, -zf) * extrude(RectangleRounded(x_n0 - x_ci + p.clip_t - 0.1 + 1.0, 2 * a_s, p.crank_vfillet), 20)
    shaft += endp
    ht = p.knob_h                                            # arm and knob tops (above the axis)
    y0, y1 = -p.arm_back, p.crank_r + p.knob_w / 2
    arm = Pos((xh + xa) / 2, (y0 + y1) / 2, (ht - zf) / 2) * Box(xa - xh, y1 - y0, ht + zf)
    arm &= Pos((xh + xa) / 2, (y0 + y1) / 2, -zf) * extrude(RectangleRounded(xa - xh, y1 - y0, p.crank_vfillet), 20)
    knob = Pos(xa - 0.5 + (p.knob_l + 0.5) / 2, p.crank_r, (ht - zf) / 2) * Box(p.knob_l + 0.5, p.knob_w, ht + zf)
    knob &= Pos(xa - 0.5 + (p.knob_l + 0.5) / 2, p.crank_r, -zf) * extrude(RectangleRounded(p.knob_l + 0.5, p.knob_w, p.knob_w / 2 - 0.01), 20)
    crank = arm + knob
    crank = _chamfer(crank, p.arm_edge_r, [e for e in crank.edges() if e.center().Z > ht - 0.05])   # crisp top edge breaks only
    part = shaft + crank
    # 45-deg flare where the shaft meets the arm (a lofted collar from the shaft section to the section grown by
    # shoulder_r): only obtuse 135-deg edges, no sharp re-entrant shoulder; clipped flat on the bed plane
    flare = loft([Plane.YZ.offset(xh - p.shoulder_r) * _quad_flat(r, zf), Plane.YZ.offset(xh + 0.01) * _quad_flat(r, zf, p.shoulder_r)])
    part += flare & _above(-zf)
    return part


def make_clip(p, L):
    """Lily-pad C-ring in the shaft frame, printed flat (ring arms bend in-layer). Two jaws rise from the
    ring's lower arms: each hugs a side of the neck (keys it, and is the shoulder the end piece pulls on),
    hooks under the neck's bottom flat with a horizontal catch face, and lips over the neck's top corner."""
    zf, sn = p.shaft_zf, L["sn"]
    x_ci, _ = _clip_x(p)
    y_t = p.neck_a - p.clip_engage - sn                     # tooth tip: engagement past the clearance gap
    z_c = -zf - sn                                          # crisp catch face (horizontal)
    ring = Pos(0, p.clip_taper) * Circle(p.clip_ro) - Circle(p.clip_ri)
    y_in = p.neck_a + sn
    yo = y_in + p.jaw_w
    zt_ = p.neck_top + sn
    zb_ = -sqrt(p.clip_ri ** 2 - yo ** 2) - 1.0
    jaw = Polygon((y_t, z_c), (y_in, z_c), (y_in, zt_), (p.neck_a - p.jaw_lip, zt_), (p.neck_a - p.jaw_lip, zt_ + p.jaw_lip_h),
                  (yo, zt_ + p.jaw_lip_h), (yo, zb_), (y_t + 1.0, zb_), (y_t, z_c - p.tooth_land), align=None)
    teeth = jaw + mirror(jaw, about=Plane.YZ)
    zl = z_c - p.tooth_land
    vee = Polygon((-y_t, zl), (y_t, zl), (y_t + 12, zl - 12), (-y_t - 12, zl - 12), align=None)
    vee += Pos(0, (z_c + zl) / 2) * Rectangle(2 * y_t, z_c - zl + 0.02)
    vee3 = _xprism(vee, x_ci - p.clip_t - 1, x_ci + 1)
    # wall-side zone: ring + jaws; outer zone: ring + jaws minus room for the shaft's end piece, so the jaw
    # roots run the full thickness (no step at the root)
    a_s = sqrt(p.shaft_r ** 2 - zf ** 2) + 0.3
    env = Pos(0, (p.shaft_r - zf) / 2) * Rectangle(2 * a_s, p.shaft_r + zf + 0.6)

    def zone(prof, x0, x1):
        sol = (_xprism(ring, x0, x1) + _xprism(prof, x0, x1)) - vee3
        f = sol.faces().sort_by(Axis.X)[-1]
        vs = [v for v in f.vertices() if abs(sqrt(v.Y ** 2 + v.Z ** 2) - p.clip_ri) < 0.1 and v.Z < -1.0]
        try:   # round the roots where the jaws meet the ring (sharp roots ~3x strain)
            return extrude(f.fillet_2d(p.clip_root_r, vs), x1 - x0, dir=(-1, 0, 0))
        except Exception:
            return sol
    return zone(teeth, x_ci - p.tooth_t, x_ci) + zone(teeth - env, x_ci - p.clip_t, x_ci - p.tooth_t + 0.01)


def make_camblock(p, L):
    """Shaft frame. Printed on its -X end (frog_1 disc face on the plate, vertical edge)."""
    e, R, hr = p.cam_e, p.cam_r, p.cam_hub_r
    x_lo = -(L["x_rib"] - p.cam_end_gap)
    x_hi = L["x_rib"] - p.cam_end_gap
    blk = _xprism(Circle(hr), x_lo, x_hi)
    cone_len = e + R - hr + p.cam_cone_extra
    for name in ("frog_1", "tongue", "frog_3"):
        x, phi = L["cam_x"][name], L["phi"][name]
        w = p.cam_w
        cy, cz = e * cos(radians(phi)), e * sin(radians(phi))
        x0, x1 = x - w / 2, x + w / 2
        if name == "tongue":
            x1 = L["fly_x1"] + 0.3
        if name == "frog_1":
            x0 = x_lo
        disc = _xprism(Pos(cy, cz) * Circle(R), x0, x1)
        blk += disc
        if name != "frog_1":
            blk += loft([Plane.YZ.offset(x0 - cone_len) * Circle(hr), Plane.YZ.offset(x0) * Pos(cy, cz) * Circle(R)])
    bore = _xprism(_quad_flat(p.shaft_r, p.shaft_zf, L["sn"]), x_lo - 1, x_hi + 1)
    return blk - bore


def make_follower(p, L):
    """Hopper follower, frame: foot bottom centre at the origin."""
    foot = extrude(RectangleRounded(p.foot_w, p.foot_d, p.foot_corner_r), p.foot_t)
    foot = _fillet(foot, p.foot_top_r, foot.edges().group_by(Axis.Z)[-1])
    rod = Pos(0, 0, p.foot_t - 0.01) * extrude(RectangleRounded(p.rod_a, p.rod_b, p.rod_corner_r), L["rod_top"] - p.foot_t + 0.01)
    rod = _chamfer(rod, p.rod_tip_chamfer, rod.edges().group_by(Axis.Z)[-1])
    f = foot + rod
    # notch for the frog's snap hook (+x side); its flat top is the catch
    zb_ = L["frog_dz"]
    z0n = zb_ + p.hook_z0 - 0.1
    z1n = round((zb_ + p.hook_z0 + p.hook_h + 0.4) / 0.2 + 0.4999) * 0.2       # catch roof on the 0.2 layer grid
    # pocket, not a through-cut: 0.6 mm cheeks either side make the roof a 3-sided bridge
    f -= Pos(p.rod_a / 2, 0, (z0n + z1n) / 2) * Box(2 * (p.clip_engage + L["sn"] + 0.1), p.rod_b - 2 * p.notch_cheek, z1n - z0n)
    f = _fillet(f, p.rod_root_r, f.edges().filter_by_position(Axis.Z, p.foot_t - 0.02, p.foot_t + 0.02)
                .filter_by(lambda e: abs(e.center().X) < p.rod_a and abs(e.center().Y) < p.rod_b))
    return f


# ---------------------------------------------------------------- hopper frog (B, with a vertical plinth)
def _yprism(prims, y0, y1):
    """Union of (x, z) sketches extruded along Y from y0 to y1 (fused in 3D: 2D sketch unions stay split)."""
    out = None
    for f in prims:
        e = extrude(Plane.XZ.offset(-y1) * f, y1 - y0, dir=(0, -1, 0))
        out = e if out is None else out + e
    return out


def _front_fillet(solid, r, y_face, z_min):
    """Fillet the edges of the face at y = y_face, except edges lying on z = z_min (a bed or a joint)."""
    es = [e for e in solid.edges() if abs(e.center().Y - y_face) < 0.02 and e.bounding_box().min.Z > z_min + 0.05]
    out = _fillet(solid, r, es)
    out = out if out is not solid else _chamfer(solid, r * 0.6, es)
    import build123d as _bd
    return _bd.Part() + out          # keep a Part: booleans with compounds misbehave on a bare Solid


def _crush_socket(w, d, r, depth, rib_r, rib_int, gap):
    """Keyed socket (rod w x d + gap) with two crush ribs on each long side (interference rib_int)."""
    sock = extrude(RectangleRounded(w + 2 * gap, d + 2 * gap, r + gap), depth)
    for sx in (-1, 1):
        for yy in (-d / 4, d / 4):
            sock -= Pos(sx * (w / 2 - rib_int + rib_r), yy, 0) * extrude(Circle(rib_r), depth)
    return sock


def make_frog(p, L):
    """Hopper frog: chunky front silhouette (body, two big eye lobes, feet bumps) extruded frog_d deep,
    printed on its flat back. Smile = one bold groove; pupils = shallow round recesses. Frog frame: rod
    axis at the origin, belly at z=0, faces -Y."""
    hw, h = p.frog_w / 2, p.frog_h
    yf, yb_ = -p.frog_d / 2, p.frog_d / 2
    prims = [Pos(0, h / 2) * RectangleRounded(2 * hw, h, min(p.frog_corner_r, h / 2 - 0.01)),
             Pos(-p.frog_eye_x, h + p.frog_eye_dz) * Circle(p.frog_eye_r), Pos(p.frog_eye_x, h + p.frog_eye_dz) * Circle(p.frog_eye_r),
             Pos(-(hw - p.frog_foot_r + 0.4), p.frog_foot_r) * RectangleRounded(2 * p.frog_foot_r, 2 * p.frog_foot_r, 1.0),
             Pos(hw - p.frog_foot_r + 0.4, p.frog_foot_r) * RectangleRounded(2 * p.frog_foot_r, 2 * p.frog_foot_r, 1.0)]
    frog = _yprism(prims, yf, yb_) & _above(0)
    frog = _front_fillet(frog, p.frog_fillet, yf, 0.0)
    g = p.smile_w
    smile = (Pos(0, p.smile_z) * (Circle(p.smile_r + g / 2) - Circle(p.smile_r - g / 2))) & Pos(0, p.smile_z - p.smile_r) * Rectangle(2 * p.smile_r * 0.82, 2 * p.smile_r * 0.9)
    frog -= _yprism([smile], yf - 1, yf + p.groove_d)
    for sx in (-1, 1):
        frog -= _yprism([Pos(sx * p.frog_eye_x, h + p.frog_eye_dz) * RegularPolygon(p.pupil_r, 8)], yf - 1, yf + p.groove_d)
    # eyes bulge forward: the back of the eye lobes tapers at 45 deg, starting 2.2 mm off the flat back
    # (the print bed), so the taper is a plain 45-deg overhang outside the bed zone
    yt = yb_ - p.eye_taper_start
    frog -= _yzsym(Polygon((yb_ + 1, h), (yt, h), (yt - 30, h + 30), (yb_ + 1, h + 30), align=None), 4 * hw)
    frog = _snap_socket(p, L, frog, yf, yb_)
    return frog


def _snap_socket(p, L, part, yf, yb_, a=None, b=None, fl=None, z0=-1.0, depth=None, t=None, gable=False, hz0=None, keep=None, sharp=False):
    """Keyed socket on a rod + hidden snap finger (frog frame: rod axis at the origin, belly z=0, back face
    y = yb_ on the print bed). The finger is a tapered cantilever along z beside the socket, rooted at
    z = fsnap_l and free at the belly; it bends in x, in the print plane (in-layer). A 1.7 mm cavity outside it
    leaves room for the full deflection; a front gap of fsnap_gap (3 layers, on a layer boundary) keeps it
    off the front skin."""
    sn = L["sn"]
    a = p.rod_a if a is None else a
    b = p.rod_b if b is None else b
    fl = p.fsnap_l if fl is None else fl
    t = p.fsnap_t if t is None else t
    depth = p.socket_depth if depth is None else depth
    sk = Rectangle(a + 2 * sn, b + 2 * sn) if sharp else RectangleRounded(a + 2 * sn, b + 2 * sn, p.rod_corner_r + sn)
    part -= Pos(0, 0, z0) * extrude(sk, depth - z0)
    if gable:   # 45-deg roof on the front (-y) side: the socket's ceiling when the part prints on its back
        ha, hb = a / 2 + sn, b / 2 + sn
        hg = ha - 1.6                            # keep clear of the finger's front gap
        part -= Pos(0, 0, z0) * extrude(Polygon((-hg, -hb + 0.01), (hg, -hb + 0.01), (0, -hb - hg), align=None), depth - z0, dir=(0, 0, 1))
    xs0 = a / 2 + sn                             # finger inner face = socket wall
    xr = xs0 + t                                 # finger outer face at the root
    xt = xs0 + t * p.fsnap_taper                 # ...and at the tip
    xo = xr + p.fsnap_cav                        # outer cavity wall
    yfs = yf + p.fsnap_skin                      # front of the cavity (skin in front of it)
    cav = [Pos((xs0 - 1.3 + xs0) / 2, (fl + z0) / 2) * Rectangle(1.3, fl - z0),
           Pos(xs0 - 0.65, fl) * Ellipse(0.65, 0.9),
           Polygon((xt, z0), (xo, z0), (xo, fl), (xr, fl), align=None),
           Pos((xr + xo) / 2, fl) * Ellipse((xo - xr) / 2, 0.9)]
    cv = _yprism(cav, yfs + p.fsnap_gap, yb_ + 0.01)
    part -= cv if keep is None else cv & keep
    # gap between the finger and the front skin; starts at x >= 1.6 and runs above the root into the eye bulk
    gz = fl + 1.6
    xg = max(1.6, xs0 - 0.5)
    gp = _yprism([Pos((xg + xo) / 2, (gz + z0) / 2) * Rectangle(xo - xg, gz - z0)], yfs, yfs + p.fsnap_gap + 0.01)
    part -= gp if keep is None else gp & keep
    hp = p.clip_engage + sn                      # hook overlap: engagement past the clearance gap
    hz0 = p.hook_z0 if hz0 is None else hz0
    hook = Polygon((xs0 + 0.01, hz0), (xs0 + 0.01, hz0 + p.hook_h), (xs0 - hp, hz0 + p.hook_h),
                   (xs0 - hp, hz0 + hp), align=None)
    part += _yprism([hook], -p.hook_w / 2, p.hook_w / 2)
    return part


# ---------------------------------------------------------------- middle frog: tongue, body, head, pin
def _tongue_pts(p, L):
    hw = p.tongue_w / 2
    Ln = L["L_rest"]
    N = _at(p, L, Ln)
    Np = (N[0] + p.neck_dy, N[1] + p.neck_dz)
    T = (N[0] + p.tip_dy, N[1] + p.tip_dz)
    return hw, Ln, N, Np, T


def make_tongue(p, L):
    """Built in the assembly frame at the lowest pose (s = s_min); placed by a shift along u."""
    hw, Ln, N, Np, T = _tongue_pts(p, L)
    s0 = L["s_min"]
    fw = p.tongue_foot_w / 2
    prof = Polygon(_at(p, L, s0, -fw), _at(p, L, s0 + p.foot_t, -fw), _at(p, L, s0 + p.foot_t, -hw),
                   _at(p, L, Ln, -hw), _at(p, L, Ln, hw), _at(p, L, s0 + p.foot_t, hw),
                   _at(p, L, s0 + p.foot_t, fw), _at(p, L, s0, fw), align=None)
    prof += Pos(*N) * Circle(hw) + _stadium(Np, T, p.tip_r)
    tongue = _yzsym(prof, p.tongue_t)
    return tongue


def _sleeve_dims(p, L):
    sl = L["sl"]
    return p.tongue_t + 2 * sl + 2 * p.sleeve_wall, p.tongue_w + 2 * sl + 2 * p.sleeve_wall


def _socket_origin(p, L):
    """Socket frame of the middle frog: z' along the tongue axis u, x' = x, origin on the axis at the pad top."""
    l_p = _l_at_z(p, L, L["z_p"])
    y, z = _at(p, L, l_p)
    return (0.0, y, z), l_p


def make_body(p, L):
    """Middle frog's body shell (green), in the socket frame. Front silhouette with haunch steps, flat mouth
    floor, hinge tab at the back. Snaps onto the deck's inclined tongue sleeve with the outer frogs' hidden
    finger. Prints on its flat back."""
    lo = L["lo"]
    zp, zm, yb = L["z_p"], L["z_m"], L["yb"]
    yback = yb + p.body_ry
    # front silhouette extruded along y (it prints on its flat back, like the outer frogs)
    body = _yprism([Pos(0, (zp + zm) / 2) * RectangleRounded(2 * p.body_rx, zm - zp, p.body_corner_r)], yb - p.body_ry, yback)
    hx = p.body_rx + p.haunch_w / 2 - 1.5
    body += _yprism([Pos(sx * hx, zp + p.haunch_h / 2) * Rectangle(p.haunch_w, p.haunch_h) for sx in (-1, 1)],
                    yb + p.haunch_dy - p.haunch_l / 2, yback)
    yh, zh = L["y_h"], L["z_h"]
    body -= Pos(0, yh - 0.6 + 20, zm - 1.4 + 20) * Box(2 * p.head_rx + 4, 40, 40)      # relief for the head's heel
    tab = _xprism(Pos(yh, zh) * Circle(p.tab_r), -p.tab_t / 2, p.tab_t / 2)
    tab += Pos(0, yh, (zm - p.tab_root + zh) / 2) * Box(p.tab_t, 2 * p.tab_r, zh - zm + p.tab_root)
    tab += Pos(0, yh + p.tab_r / 2, zh + p.tab_r / 2) * Box(p.tab_t, p.tab_r, p.tab_r)       # square back-top: vertical at the print bed
    body += tab & Pos(0, yback - 50, 0) * Box(200, 100, 200)                     # flat with the back face (print bed)
    # pivot hole roof points to print-up (assembly -Y: the shell prints on its back)
    body -= _xprism(Pos(yh, zh) * Rot(0, 0, 90) * _bearing_hole(p.pin_r + lo), -p.tab_t, p.tab_t)
    body -= Pos(0, yb - 1.5, zm - p.floor_pocket_d) * extrude(RectangleRounded(p.body_rx * 1.1, p.body_ry * 0.9, 1.0), p.floor_pocket_d + 1)
    hw, Ln, N, Np, T = _tongue_pts(p, L)
    travel = 2 * p.cam_e
    dd = (travel * L["u"][0], travel * L["u"][1])
    gg = p.groove_gap
    O, l_p = _socket_origin(p, L)
    body -= _tongue_prism(p, L, l_p + p.body_sock_d - 0.5, Ln + travel + 6, hw + gg, p.tongue_t / 2 + gg)
    body -= _yzsym(_swept_stadium(Np, T, p.tip_r + gg, dd), p.tongue_t + 2 * gg)
    body -= _yzsym(_swept_stadium(N, N, hw + gg, dd), p.tongue_t + 2 * gg)
    nz0 = T[1] - p.tip_r - gg
    y_lip = yb - p.body_ry - p.notch_margin
    body -= Pos(0, (T[0] + y_lip) / 2, (nz0 + zm + 5) / 2) * Box(p.tongue_t + 2 * gg, T[0] - y_lip, zm + 5 - nz0)
    # into the socket frame, then the snap socket over the sleeve
    body = Rot(-p.tongue_beta, 0, 0) * (Pos(0, -O[1], -O[2]) * body)
    A, B = _sleeve_dims(p, L)
    # finger cavities stay 2.4 mm under the mouth floor (assembly z); otherwise their tops break out at the back
    keep = Rot(-p.tongue_beta, 0, 0) * (Pos(0, -O[1], -O[2]) * (Pos(0, 0, zm - p.body_cav_drop - 50) * Box(200, 200, 100)))
    return _snap_socket(p, L, body, -(B / 2 + L["sn"]) - 0.5 - p.fsnap_skin, 40, a=A, b=B, fl=p.body_fsnap_l,
                        z0=-8.0, depth=p.body_sock_d, t=p.body_fsnap_t, gable=True, hz0=p.body_hook_z0, keep=keep, sharp=True)


def make_sleeve(p, L):
    """Deck's inclined tongue sleeve (assembly frame): the tongue slides inside it, the body shell snaps over it."""
    A, B = _sleeve_dims(p, L)
    sn = L["sn"]
    sl_ = Pos(0, 0, -12) * extrude(RectangleRounded(A, B, p.rod_corner_r), p.body_sock_d - sn + 12)
    sl_ = _chamfer(sl_, p.rod_tip_chamfer, sl_.edges().group_by(Axis.Z)[-1])
    hp = p.clip_engage + sn
    z0n, z1n = p.body_hook_z0 - 0.1, p.body_hook_z0 + p.hook_h + 0.4
    sl_ -= Pos(A / 2, 0, (z0n + z1n) / 2) * Box(2 * (hp + 0.1), B - 2 * p.notch_cheek, z1n - z0n)
    O, _ = _socket_origin(p, L)
    return (Pos(*O) * (Rot(p.tongue_beta, 0, 0) * sl_)) & _above(L["deck_top"] - 1.0)


def _pin_hole(p, L, press):
    """Keyed pin hole in the head (y, z in head frame): pin section + snug, 45-deg roof; crush ribs on
    the vertical side flats when press=True."""
    sn = L["sn"]
    a = sqrt(p.pin_r ** 2 - p.pin_zf ** 2) + sn
    rr = p.pin_r + sn
    top = rr * sqrt(2)
    f = Polygon((-a, -p.pin_zf - sn), (a, -p.pin_zf - sn), (a, top - a), (0, top), (-a, top - a), align=None)
    if press:
        for sx in (-1, 1):
            f -= Pos(sx * (a - sn - p.rib_int + p.rib_r), 0) * Circle(p.rib_r)
    return f


def make_head(p, L):
    """Head frame: hinge axis = X through the origin, palate at z = -hinge_c. Front silhouette (dome + two eye
    lobes, pupils on the front, like the outer frogs) extruded from the lips back to a flat rear face behind the
    hinge; prints on that rear face. The backs of the eye lobes taper at 45 deg."""
    c = p.hinge_c
    yh = L["y_h"]
    yf = L["yb"] - p.body_ry - 0.3 - yh
    ze = -c + p.head_rz + p.eye_dz
    prims = [Pos(0, -c) * Ellipse(p.head_rx, p.head_rz),
             Pos(-p.eye_x, ze) * Circle(p.eye_r), Pos(p.eye_x, ze) * Circle(p.eye_r)]
    head = _yprism(prims, yf, c) & _above(-c)
    head = _front_fillet(head, p.frog_fillet, yf, -c)
    ztop = -c + p.head_rz
    yt = c - p.eye_taper_start
    head -= _yzsym(Polygon((c + 1, ztop), (yt, ztop), (yt - 30, ztop + 30), (c + 1, ztop + 30), align=None), 4 * p.head_rx)
    for sx in (-1, 1):
        head -= _yprism([Pos(sx * p.eye_x, ze + 0.25 * p.eye_r) * RegularPolygon(p.pupil_r, 8)], yf - 1, yf + p.groove_d)
    sr = p.tab_r + p.slot_gap
    sxw = p.tab_t + 2 * p.slot_gap
    head -= _xprism(Circle(sr), -sxw / 2, sxw / 2)
    head -= Pos(0, p.slot_back / 2, -c / 2 - 0.5) * Box(sxw, 2 * sr + p.slot_back, c + 1)
    head -= Pos(0, (-sr + c + 1) / 2, 0) * Box(sxw, sr + c + 1, 40)           # slot open to the top: no grazing knife edge
    # pin hole: the pin's rounded square + snug; crush ribs on the +-z flats (vertical in print: they crush
    # in-layer); the -y flat is the hole's ceiling in print (a short bridge)
    sn = L["sn"]
    hole = _quad_flat(p.pin_r, p.pin_zf, sn)
    for sz in (-1, 1):
        hole -= Pos(0, sz * (p.pin_zf + sn + p.rib_r - p.rib_int - sn)) * Circle(p.rib_r)
    head -= _xprism(hole, -2 * p.head_rx, 2 * p.head_rx)
    return head


def make_pin(p, L):
    pin = _xprism(_quad_flat(p.pin_r, p.pin_zf), -p.pin_l / 2, p.pin_l / 2)
    pin = _chamfer(pin, p.pin_chamfer, [e for e in pin.edges() if abs(abs(e.center().X) - p.pin_l / 2) < 0.02
                                        and e.center().Z > -p.pin_zf + 0.2])
    return pin


# ---------------------------------------------------------------- fly
def make_fly(p, L):
    """Fly follower as one side silhouette (y, z) extruded fly_t thick along X, printed lying on its side:
    L-plate foot on the tongue cam, keyed rod up through the deck, a stalk, and the fly (body, head, wing).
    Frame: plate bottom at z=0, x/y as in the assembly."""
    ys = L["ys"]
    fy = ys + p.fly_rod_dy
    x0, x1 = L["fly_x0"], L["fly_x0"] + p.fly_t
    zf0 = L["zf_min"]
    z_fly = L["z_m"] + p.fly_dz - zf0
    z_rod = L["pad_top"] - p.pad_h * 0.5 + 0.6 - zf0
    yfl = ys + p.fly_dy
    prims = [Pos((fy - p.rod_b / 2 - 1.0 + ys + p.cam_e + 1.5) / 2, p.fly_plate_t / 2) * Rectangle(ys + p.cam_e + 1.5 - (fy - p.rod_b / 2 - 1.0), p.fly_plate_t),
             Pos(fy, z_rod / 2) * Rectangle(p.rod_b, z_rod),
             Polygon((fy - p.stalk_w / 2 - 1.0, z_rod - 0.01), (fy + p.stalk_w / 2 + 1.0, z_rod - 0.01),
                     (yfl + p.stalk_w / 2, z_fly), (yfl - p.stalk_w / 2, z_fly), align=None),
             Pos(yfl, z_fly) * Ellipse(p.fly_ry, p.fly_rz),
             Pos(yfl - p.fly_ry - 0.6, z_fly + 0.5) * Circle(p.fly_rz * 0.85),
             Pos(yfl - 1.2, z_fly + p.fly_rz + 1.0) * Rot(0, 0, 25) * Ellipse(p.fly_ry * 0.95, p.fly_rz * 0.7),
             Pos(yfl + 1.6, z_fly + p.fly_rz + 0.8) * Rot(0, 0, -30) * Ellipse(p.fly_ry * 0.95, p.fly_rz * 0.7)]
    out = None
    for k, f in enumerate(prims):
        e = _xprism(f, x0, x1) if k < 3 else _xprism(f, x1 - p.fly_plate, x1)   # the fly itself: a 2 mm plate on the bed side (+X down)
        out = e if out is None else out + e
    return out


# ---------------------------------------------------------------- design
def _shapes(p, L):
    import hashlib
    import sys
    from pathlib import Path
    cache = sys.__dict__.setdefault("_forge_automaton_cache", {})
    key = hashlib.sha256(Path(__file__).read_bytes() + repr(sorted(
        (k, v) for k, v in vars(p).items() if k != "crank_deg")).encode()).hexdigest()
    if key not in cache:
        cache.clear()
        cache[key] = dict(base=make_base(p, L), deck=make_deck(p, L), crankshaft=make_crankshaft(p, L),
                          clip=make_clip(p, L), camblock=make_camblock(p, L), follower=make_follower(p, L),
                          frog=make_frog(p, L), tongue=make_tongue(p, L), body=make_body(p, L),
                          head=make_head(p, L), pin=make_pin(p, L), fly=make_fly(p, L), L=dict(L))
    return cache[key]


def build(p) -> Design:
    L = _layout(p)
    S = _shapes(p, L)
    L.update(S["L"])
    a = p.crank_deg
    ys, zs = L["ys"], p.shaft_z
    rot_shaft = ((0, ys, zs), (a, 0, 0))
    ds = _tongue_ds(p, L)
    u = L["u"]
    alpha = _head_angle(p, L, ds)
    head_pl = ((0, L["y_h"], L["z_h"]), (-alpha, 0, 0))
    fly_z = _foot_z(p, L, "fly")
    W = p.base_w

    parts = [
        Part("base", S["base"], color="#2A8FA0", orient=(0, 0, 0), cosmetic=["-y", "+y", "-x", "+x"],
             notes="Pond ring, printed upright (open top and bottom). Bearing holes: 90-deg round bottom arc + tangent flanks + 45-deg roof."),
        Part("deck", S["deck"], color="#3BA7A0", orient=(0, 0, 0), cosmetic=["+z"],
             notes="Pond surface, printed top-up: raised lily pads, the inclined tongue sleeve (the body shell snaps over it), two in-plane snap fingers."),
        Part("crankshaft", S["crankshaft"], color="#C8743A", placement=rot_shaft, orient=(0, 0, 0), cosmetic=["+x"],
             notes="Shaft, leaf arm and knob in one, lying on the shared bottom flat (triple-flat section)."),
        Part("clip", S["clip"], color="#5FAE4A", placement=rot_shaft, orient=(0, 90, 0), cosmetic=["-x"],
             notes="Lily-pad C-ring snapped radially onto the keyed neck at the -X end; stops the shaft pulling out."),
        Part("camblock", S["camblock"], color="#F2B134", placement=rot_shaft, orient=(0, -90, 0),
             notes="Four eccentrics on one hub; printed on its -X disc."),
        Part("tongue", S["tongue"], color="#E8607F", placement=((0, ds * u[0], ds * u[1]), (0, 0, 0)), orient=(0, 90, 0),
             notes="Inclined follower; its round top pushes the palate, the tip is the tongue. Prints on its side."),
        Part("body", S["body"], color="#4F9D3A", placement=(_socket_origin(p, L)[0], (p.tongue_beta, 0, 0)),
             orient=(p.tongue_beta - 90, 0, 0), cosmetic=["-y"],
             notes="Middle frog's body shell (socket frame along the tongue axis). Snaps over the deck's inclined tongue sleeve; prints on its flat back."),
        Part("head", S["head"], color="#7CC142", placement=head_pl, orient=(-90, 0, 0), cosmetic=["-y"],
             notes="Upper jaw: front silhouette with eye lobes and pupils; prints on its flat rear face. Gravity keeps it on the tongue."),
        Part("pin", S["pin"], color="#7CC142", placement=head_pl, orient=(0, 0, 0),
             notes="Hinge pin, press-fit (crush ribs) in the head, loose in the body tab. Lies on its flat."),
        Part("fly", S["fly"], color="#2B2B33", placement=(0, 0, fly_z), orient=(0, 90, 0),
             notes="Fly follower: L-plate foot on its own cam, keyed rod, leaning stalk, fly."),
    ]
    sw = p.shaft_r + 1.5
    fits = [
        Fit("crankshaft", "base", "loose",
            region=Region((-W / 2 - 0.2, ys - sw, zs - sw), (W / 2 + 0.2, ys + sw, zs + sw)), retention="captured",
            notes="Both journals in their bearing holes (round bottom arc + roof). Captured: hub shoulder at +X, snap clip at -X."),
        Fit("camblock", "crankshaft", "snug", retention="captured", notes="Rounded-square key; captured between the bearing ribs (0.4 mm each side)."),
        Fit("clip", "crankshaft", "snug", retention="snap", snap_case="clip_snap", notes="Keyed on the neck; the teeth overlap the neck by 1.1 mm."),
        Fit("deck", "base", "contact", retention="snap", snap_case="deck_snap_left", notes="Deck rests on the ledge; front tabs hook under pockets, two back fingers snap (deck_snap_left / deck_snap_right, mirror twins)."),
        Fit("tongue", "camblock", "contact", drives=True),
        Fit("body", "deck", "snug", retention="snap", snap_case="body_snap",
            region=Region((-6, -14, L["z_p"] + 0.5), (6, 4, L["z_p"] + p.body_sock_d)), notes="Shell over the inclined tongue sleeve; hidden finger hooks the sleeve notch."),
        Fit("tongue", "deck", "sliding", region=Region((-5, -40, L["deck_bot"] - 0.5), (5, 40, L["z_p"] + p.body_sock_d * 0.9)),
            retention="captured", notes="Inclined keyed guide through deck and body; the foot is the stop under the deck."),
        Fit("head", "tongue", "contact", drives=True, notes="Round tongue top pushes the flat palate; 0.1 mm running gap."),
        Fit("head", "pin", "press", overlap_ok_mm3=3.0, retention="press", notes="Crush ribs on the pin's side flats."),
        Fit("pin", "body", "loose", region=Region((-p.tab_t / 2 - 0.3, L["y_h"] - 5, L["z_h"] - 5), (p.tab_t / 2 + 0.3, L["y_h"] + 5, L["z_h"] + 5)),
            retention="captured", notes="Head pivot. Pin pressed in the head and captured axially between the two hopper frogs (end play 3 mm at every pose)."),
        Fit("fly", "camblock", "contact", drives=True),
        Fit("fly", "deck", "sliding", region=Region((L["fly_x0"] - 2, ys + p.fly_rod_dy - 4, L["deck_bot"] + 0.2),
                                                     (L["fly_x0"] + p.fly_t + 2, ys + p.fly_rod_dy + 4, L["deck_top"] + p.pad_h * 0.5 - 0.2)),
            retention="captured", notes="Keyed rod; the L-plate foot is the stop under the deck."),
    ]
    for i, name in ((0, "frog_1"), (2, "frog_3")):
        x = L["xs"][i]
        zf = _foot_z(p, L, name)
        fn, gn = f"follower_{i + 1}", name
        parts.append(Part(fn, S["follower"], color="#6A994E", placement=(x, ys, zf), orient=(0, 0, 0),
                          notes="Foot + keyed rod; the foot is the stop under the deck."))
        parts.append(Part(gn, S["frog"], color=["#5DBB4A", "#3FA34D"][i // 2], placement=(x, ys, zf + L["frog_dz"]),
                          orient=(-90, 0, 0), cosmetic=["-y"], notes="2.5D silhouette, printed on its flat back; snaps onto the rod tip (hidden finger, in-layer)."))
        fits += [
            Fit("camblock", fn, "contact", drives=True),
            Fit(fn, "deck", "sliding", region=Region((x - 4, ys - 4, L["deck_bot"] + 0.2), (x + 4, ys + 4, L["pad_top"] - 0.2)),
                retention="captured", notes="Keyed rod in the pad guide; the foot is the stop under the deck."),
            Fit(gn, fn, "snug", retention="snap", snap_case=f"{gn}_snap", notes="Snap finger in the frog hooks a notch in the rod tip."),
        ]
    return Design(
        parts=parts, fits=fits, loads=_loads(p, L),
        explode={"deck": (0, 0, 22), "head": (0, 0, 48), "pin": (14, 0, 48),
                 "frog_1": (0, 0, 40), "frog_3": (0, 0, 40), "follower_1": (0, 0, 14), "follower_3": (0, 0, 14),
                 "tongue": (0, -8, 30), "fly": (0, -14, 14), "camblock": (0, 0, -30), "crankshaft": (34, 0, -30),
                 "clip": (-16, 0, -30)},
        motion=Motion("crank_deg", -90, 270, 15, min_travel_mm=6, min_travel_deg=20,
                      exclude_travel=("crankshaft", "camblock", "clip")),
    )


def _R(xr, rest):
    (x0, x1), (y0, y1, z0, z1) = xr, rest
    return Region((min(x0, x1), y0, z0), (max(x0, x1), y1, z1))


def _loads(p, L):
    W, zf = p.base_w, p.shaft_zf
    xa = W / 2 + p.hub_gap + p.crank_t
    jr = p.shaft_r + 0.6
    x_ci, _ = _clip_x(p)
    y_t = p.neck_a - p.clip_engage - L["sn"]
    z_c = -zf - L["sn"]
    zb, zt = L["deck_bot"], L["deck_top"]
    ye = L["y_in"] - p.deck_gap
    x_tip = p.fing_root_x + p.fing_l
    y_lip = ye + p.lip_p

    def _bx(sx, a, b):          # helper: x-range [a, b] on the side sx, packed with (y0, y1, z0, z1) below
        return (sx * a, sx * b) if sx > 0 else (-b, -a)
    xs0 = p.rod_a / 2 + L["sn"]
    hp = p.clip_engage + L["sn"]
    frog_cases = [LoadCase(f"{g}_snap", part=g,
                           fixed=Region((-p.frog_w, -p.frog_d, p.fsnap_l + 1.0), (p.frog_w, p.frog_d, 30)),
                           load=Region((xs0 - hp - 0.05, -p.hook_w / 2, p.hook_z0 + p.hook_h - 0.45), (xs0 - hp + 0.1, p.hook_w / 2, p.hook_z0 + p.hook_h - 0.05)),
                           displacement=(hp, 0, 0), nonlinear=True, use="repeated", min_force_n=5, max_force_n=15,   # engagement 1.0 + 0.1 margin
                           mesh_size=0.5, refine=Region((0.5, -p.frog_d / 2 - 0.5, -0.5), (xs0 + p.fsnap_t + p.fsnap_cav + 0.5, p.frog_d / 2 + 0.5, p.fsnap_l + 1.5)),
                           notes="Rod corner passing the hook tip: a line along Y on the hook land; frog body above the finger root fixed.")
                  for g in ("frog_1", "frog_3")]
    A, B = _sleeve_dims(p, L)
    xb0 = A / 2 + L["sn"]
    body_case = LoadCase("body_snap", part="body",
                         fixed=Region((-20, -30, p.body_fsnap_l + 1.0), (20, 30, 40)),
                         load=Region((xb0 - hp - 0.05, -p.hook_w / 2, p.body_hook_z0 + p.hook_h - 0.45), (xb0 - hp + 0.1, p.hook_w / 2, p.body_hook_z0 + p.hook_h - 0.05)),
                         displacement=(hp, 0, 0), nonlinear=True, use="repeated", min_force_n=5, max_force_n=15,
                         mesh_size=0.5, refine=Region((xb0 - 1.6, -B / 2 - 3, -8), (xb0 + p.body_fsnap_t + p.fsnap_cav + 0.5, 14, p.body_fsnap_l + 1.5)),
                         notes="Socket frame (z along the tongue axis). Sleeve corner passing the hook tip; shell above the finger root fixed.")
    return frog_cases + [body_case] + [
        LoadCase("crank_push", part="crankshaft",
                 # +X support ends 3.4 mm inboard of the hub shoulder (x = W/2 - wall), not at the bearing's outer
                 # face 0.4 mm from it: a rigid clamp there plus the re-entrant shoulder made a 0.4 mm ligament with
                 # two singular edges (31.7 MPa, 32% mesh delta). The overhang M and T at the shoulder depend only on
                 # loads outboard of it, so this changes nothing physical there.
                 fixed=[Region((-W / 2, -jr, -jr), (-W / 2 + p.wall + p.rib_t, jr, jr)),
                        Region((W / 2 - p.wall - p.rib_t, -jr, -jr), (W / 2 - p.wall, jr, jr))],
                 load=Region((xa + p.knob_l / 2, p.crank_r - p.knob_w / 2 - 0.1, -zf - 0.1), (xa + p.knob_l + 0.1, p.crank_r + p.knob_w / 2 + 0.1, p.knob_h + 0.1)),
                 force=(0, 0, -10), use="static", mesh_size=0.2,
                 refine=Region((W / 2 + p.hub_gap - 1.2, -jr, -jr), (W / 2 + p.hub_gap + 0.8, jr, jr)),   # tight box on the filleted shoulder
                 notes="10 N tangential push on the outer half of the knob; -X journal fixed, +X journal fixed only inboard of "
                       "x = W/2 - wall (support kept 3.4 mm off the hub shoulder). Shaft lies on its flat in print. Headline peak = the "
                       "SHARP shaft-to-hub shoulder, a CAD singularity that cannot converge; converged stub stress 1-3 mm away "
                       "gives nominal SF 3.6. R7 is not demonstrated until the shoulder has a fillet."),
        # No symmetry slab: the -Y tooth's contact line is held and the +Y tooth's line is moved by twice the
        # per-side spread. That equals both teeth spreading +-d (plus a rigid shift), with the same force per
        # tooth, and leaves the ring back free (the old all-DOF slab at y=0 also pinned z and x there).
        LoadCase("clip_snap", part="clip",
                 fixed=Region((x_ci - p.tooth_t - 0.05, -y_t - 0.12, z_c - 0.35), (x_ci + 0.05, -y_t + 0.05, z_c + 0.05)),
                 load=Region((x_ci - p.tooth_t - 0.05, y_t - 0.05, z_c - 0.35), (x_ci + 0.05, y_t + 0.12, z_c + 0.05)),
                 displacement=(0, 2 * (p.neck_a - y_t + 0.1), 0), nonlinear=True, use="repeated", min_force_n=5, max_force_n=15,
                 steps=5,   # 3 Newton iterations per increment at 10 steps; 5 keeps the 0.26 mm convergence mesh under ccx's 30 min
                 mesh_size=0.4, refine=Region((x_ci - p.clip_t - 0.5, -p.clip_ro - 0.5, -p.clip_ro - 0.5), (x_ci + 0.5, p.clip_ro + 0.5, p.clip_ro + 0.5)),
                 notes="Neck corners passing both tooth tips: lines along X on the tooth lands. -Y line held, +Y line moved 2x the per-side spread (= symmetric spread + rigid shift); force is per tooth."),
        LoadCase("deck_snap_left", part="deck",
                 fixed=_R((-(x_tip + 3.0), x_tip + 3.0), (ye - 9.0, ye - p.fing_t - p.fing_slot - 2.0, zb - 0.1, zt + 0.1)),
                 load=_R(_bx(-1, x_tip - p.lip_len + 0.1, x_tip - 0.1), (y_lip - 0.05, y_lip + 0.05, zb + 0.5, zb + 1.5)),
                 displacement=(0, -(p.lip_p - p.deck_gap + 0.1), 0), nonlinear=True, use="repeated", min_force_n=5, max_force_n=15,
                 mesh_size=0.4, refine=_R(_bx(-1, -(p.fing_root_x + 2), x_tip + 2), (ye - p.fing_t - p.fing_slot - 1.5, ye + p.lip_p + 0.5, zb - 0.5, zt + 0.5)),
                 notes="Back left snap finger: ring wall line on the lip's outer face while the deck is pressed in. Deck body (full width) fixed 2 mm "
                       "inboard of the slot along the finger (the old block clamped the back edge 1.5 mm from the root and made "
                       "the headline peak)."),
        LoadCase("deck_snap_right", part="deck",
                 fixed=_R((-(x_tip + 3.0), x_tip + 3.0), (ye - 9.0, ye - p.fing_t - p.fing_slot - 2.0, zb - 0.1, zt + 0.1)),
                 load=_R(_bx(1, x_tip - p.lip_len + 0.1, x_tip - 0.1), (y_lip - 0.05, y_lip + 0.05, zb + 0.5, zb + 1.5)),
                 displacement=(0, -(p.lip_p - p.deck_gap + 0.1), 0), nonlinear=True, use="repeated", min_force_n=5, max_force_n=15,
                 mesh_size=0.4, refine=_R(_bx(1, -(p.fing_root_x + 2), x_tip + 2), (ye - p.fing_t - p.fing_slot - 1.5, ye + p.lip_p + 0.5, zb - 0.5, zt + 0.5)),
                 notes="Back right snap finger: ring wall line on the lip's outer face while the deck is pressed in. Deck body (full width) fixed 2 mm "
                       "inboard of the slot along the finger (the old block clamped the back edge 1.5 mm from the root and made "
                       "the headline peak). Both lips loaded together (test run): 4.7 N per finger, 9.4 N total, 1.10%."),
    ]
