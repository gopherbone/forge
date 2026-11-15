"""Mutilated Pinion Shuttle (Brown 1868, movement 114): parametric design. Every dimension is p.<param>.

How it works
  The pinion (z teeth, only `sector_teeth` of them kept, in a symmetric sector) turns with the crank.
  The stadium frame carries a straight rack on the inner edge of its top bar (teeth down) and one on
  its bottom bar (teeth up), pitch lines one pinion pitch diameter apart. Crank counter-clockwise seen
  from the front: while the sector passes the top it drives the top rack (frame moves -X), while it
  passes the bottom it drives the bottom rack (frame moves +X). Between, the plain arc passes both
  racks and the frame rests (dwell). The sector is less than half the rim, so the racks are never
  both engaged.

Frames: desk z=0, the front is -Y, the frame occupies y in [-frame_t, 0], pinion axis at x=0, z=axis_h.
Pinion, crank and cap are modelled about their axis (origin) and placed by rotation; the frame is
modelled centred at the origin and placed by translation; base and posts in assembly coordinates.
"""
from math import cos, degrees, pi, radians, sin, sqrt, tan

from build123d import *

from forge.config import fits_table
from forge.dsl import Design, Fit, LoadCase, Motion, Part, Region

TXT = dict(font_style=FontStyle.BOLD)
CAP = 0.715          # cap height / font size for the default bold font


# ---------------------------------------------------------------- helpers
def xz(face, y0, y1):
    """Extrude a sketch drawn in (x, z) between world y0 < y1."""
    return Rot(90, 0, 0) * Pos(0, 0, -y1) * extrude(face, y1 - y0)


def yz(face, x0, x1):
    """Extrude a (y, z) sketch along +X from x0 to x1."""
    return extrude(Plane.YZ.offset(x0) * face, x1 - x0, dir=(1, 0, 0))


def tri_flat(r, zf, cx=0.0, cz=0.0):
    """(x, z) section of a round printed lying on a flat at z = cz - zf, with vertical side flats
    where the circle meets the bed plane (nothing rounds off the plate)."""
    a = sqrt(r * r - zf * zf)
    top = r + 1
    return Pos(cx, cz) * Circle(r) & Pos(cx, cz + (top - zf) / 2) * Rectangle(2 * a, top + zf)


def tri_flat_off(r, zf, off):
    a = sqrt(r * r - zf * zf) + off
    top = r + off + 1
    return Circle(r + off) & Pos(0, (top - zf - off) / 2) * Rectangle(2 * a, top + zf + off)


def tangent_pt(r, a1, a2):
    n1 = (cos(radians(a1)), sin(radians(a1)))
    n2 = (cos(radians(a2)), sin(radians(a2)))
    k = r / (1 + n1[0] * n2[0] + n1[1] * n2[1])
    return ((n1[0] + n2[0]) * k, (n1[1] + n2[1]) * k)


def bearing_hole(rh, cx=0.0, cz=0.0, arc_half=85.0):
    """Horizontal bearing hole in (x, z): round bottom arc carries the shaft, 45-deg roof (no droop)."""
    lo, hi = 270 - arc_half, 270 + arc_half
    P = lambda a: Vector(rh * cos(radians(a)), rh * sin(radians(a)), 0)
    pts = [P(hi), Vector(*tangent_pt(rh, 45, hi), 0), Vector(*tangent_pt(rh, 135, 45), 0),
           Vector(*tangent_pt(rh, lo, 135), 0), P(lo)]
    edges = [Edge.make_three_point_arc(P(lo), P(270), P(hi))]
    edges += [Edge.make_line(pts[k], pts[k + 1]) for k in range(4)]
    return Pos(cx, cz) * Face(Wire(edges))


def _try(fn, shape):
    try:
        out = fn(shape)
        ok = out is not None and out.is_valid and abs(out.volume - shape.volume) < 0.05 * shape.volume
        return out if ok else shape
    except Exception:
        return shape


def chamfer(shape, d, edges):
    return _try(lambda s: s.chamfer(d, None, edges), shape) if edges else shape


def fillet2d(face, r, verts):
    """2D fillet on a single-face sketch (Sketch has no fillet_2d, so work on its face)."""
    try:
        face = face.faces()[0] if len(face.faces()) == 1 else face
        out = face.fillet_2d(r, verts) if verts else face
        return out if out.is_valid else face
    except Exception:
        return face


# ---------------------------------------------------------------- layout
def layout(p):
    ft = fits_table()
    L = dict(sn=ft["snug"]["gap"], sl=ft["sliding"]["gap"], lo=ft["loose"]["gap"])
    m, z = p.module, p.teeth
    al = radians(p.pressure_angle)
    r = m * z / 2
    L.update(m=m, z=z, al=al, r=r, ra=r + p.pinion_addendum, pitch=pi * m, tau=2 * pi / z)
    L["ded_p"] = p.rack_addendum + p.blank_clear          # pinion dedendum: root circle = plain arc
    L["rf"] = r - L["ded_p"]
    L["hf_r"] = p.pinion_addendum + p.tip_clear            # rack root depth below its pitch line
    gap_n = L["sl"] + p.flank_extra                        # normal flank gap, all taken by the rack
    s_r = L["pitch"] / 2 - 2 * gap_n / cos(al)
    L["ht"] = s_r / 2 - p.rack_addendum * tan(al)          # rack tooth half widths: tip, root
    L["hr"] = s_r / 2 + L["hf_r"] * tan(al)
    # frame (axis-relative): rack root lines = inner straight edges of the stadium
    L["R_in"] = r + L["hf_r"]
    L["R_out"] = L["R_in"] + p.bar_w
    L["Ls"] = p.rack_teeth * L["pitch"]                    # straight inner edge = rack length (gap at each end)
    L["rc_in"] = p.end_r                                   # window corner radius (engraving: rounded rectangle)
    L["rc_out"] = p.end_r + p.bar_w
    L["Lw"] = L["Ls"] + 2 * p.rack_margin                  # window straight length (plain run past each rack end)
    L["x_end"] = L["Lw"] / 2 + L["rc_out"]                 # frame end face
    T = p.half_travel
    # the flare's tangent point on the rod lies beyond the end apex: the post starts past it
    L["x_flare"] = L["x_end"] + p.flare_r
    L["x_pi"] = max(L["x_end"], L["x_flare"]) + T + p.end_clear   # post inner face
    L["x_po"] = L["x_pi"] + p.post_t
    L["x_rod"] = L["x_po"] + T + p.rod_extra               # rod tip (frame coords)
    # y stack (front is -Y)
    L["y_ff"], L["y_fb"] = -p.frame_t, 0.0
    L["y_pc"] = -p.frame_t / 2
    L["y_pf"], L["y_pb"] = L["y_pc"] - p.pinion_t / 2, L["y_pc"] + p.pinion_t / 2
    L["y_p0"] = L["y_fb"] + p.frame_gap                    # pillar front
    L["y_p1"] = L["y_p0"] + p.pillar_t                     # pillar back
    L["y_boss"] = L["y_pb"] + L["lo"]                      # boss front (pinion thrust face)
    L["y_hub"] = L["y_p1"] + L["lo"]                       # crank hub front (thrust on the pillar back)
    L["y_arm"] = L["y_hub"] + p.hub_l                      # arm front face
    L["y_armb"] = L["y_arm"] + p.crank_t
    L["y_knob"] = L["y_armb"] + p.knob_l
    # shaft snap: slit from the boss face forward; barb catches on the hub cap's counterbore floor
    L["y_root"] = L["y_boss"]
    L["y_catch"] = L["y_root"] - p.shaft_snap_L
    L["y_shaft"] = L["y_catch"] - p.barb_land - p.snap_e - 0.2      # shaft tip
    L["y_cb"] = L["y_catch"] + L["sn"]                              # counterbore floor
    L["y_cf"] = L["y_shaft"] - 0.1                                  # cap front (shaft tip just recessed)
    zg = p.axis_h
    L["zg"] = zg
    # base footprint
    L["bx"] = L["x_po"] + p.base_margin
    L["by0"] = L["y_ff"] - p.base_front
    L["by1"] = L["y_p1"] + p.base_back
    # posts
    L["pr0"] = p.prong_slit / 2                        # prong inner face (from the post centre plane)
    L["pr1"] = L["pr0"] + p.prong_t                    # prong outer face
    L["pw"] = L["pr1"] + p.prong_gap + p.post_side     # post half width
    L["post_y0"] = L["y_pc"] - L["pw"]
    L["post_y1"] = L["y_pc"] + L["pw"]
    L["z_ledge"] = p.base_h - p.slot_len               # catch ledge (roof of the underside pocket)
    L["z_catch"] = L["z_ledge"] - p.catch_gap
    L["ramp_h"] = p.snap_e / tan(radians(p.hook_lead))   # 30-deg lead-in: two prongs push ~13 N, not ~22 N
    L["z_tip"] = L["z_catch"] - p.hook_land - L["ramp_h"]
    L["post_top"] = zg + p.rod_w / 2 + L["sl"] + p.post_roof
    return L


def frame_x(p, L, th):
    """Frame position (mm) at pinion angle th (deg): driven by the top rack around 90, by the bottom
    rack around 270, at rest at +-T in between."""
    T, r = p.half_travel, L["r"]
    th = th % 360
    x = -r * radians(th - 90) if th < 180 else r * radians(th - 270)
    return max(-T, min(T, x))


# ---------------------------------------------------------------- parts
def rack_teeth(p, L, top):
    """Bottom-rack tooth trapezoids in frame (x, z), gap centred at u=0; the top rack is the point mirror."""
    out = None
    zp, ha, hf = -L["r"], p.rack_addendum, L["hf_r"]
    n = p.rack_teeth
    for k in range(-n // 2, n - n // 2):
        uc = L["pitch"] / 2 + k * L["pitch"]
        pts = [(uc - L["hr"], zp - hf - 0.05), (uc + L["hr"], zp - hf - 0.05),
               (uc + L["ht"], zp + ha), (uc - L["ht"], zp + ha)]
        t = Polygon(*pts, align=None)
        if top:
            t = Rot(0, 0, 180) * t
        out = t if out is None else out + t
    return out


def make_frame(p, L):
    Ls, Ro, Ri = L["Ls"], L["R_out"], L["R_in"]
    Lw = L["Lw"]
    outer = RectangleRounded(2 * L["x_end"], 2 * Ro, L["rc_out"])
    rod = Pos(0, 0) * Rectangle(2 * L["x_rod"], p.rod_w)
    face = outer + rod
    # flare: concave fillets where the rods neck into the ends
    xj = L["x_end"]
    neck = [v for v in face.vertices() if abs(abs(v.Y) - p.rod_w / 2) < 1e-3 and abs(abs(v.X) - xj) < 0.05]
    face = fillet2d(face, p.flare_r, neck)
    assert abs(face.area - (outer + rod).area) > 0.5, "rod flare fillet failed"
    tips = [v for v in face.vertices() if abs(abs(v.X) - L["x_rod"]) < 1e-3]
    face = fillet2d(face, p.rod_tip_r, tips)
    face -= RectangleRounded(Lw + 2 * L["rc_in"], 2 * Ri, L["rc_in"])
    face += rack_teeth(p, L, False) + rack_teeth(p, L, True)
    body = xz(face, L["y_ff"], L["y_fb"])
    # finish the up-facing (front) outer edge: a small flat chamfer, never a round
    yf = L["y_ff"]
    edges = body.edges().filter_by(lambda e: abs(e.center().Y - yf) < 1e-3 and
                                   (abs(e.center().Z) > Ri + 0.5 or abs(e.center().X) > Lw / 2 + L["rc_in"] + 0.5))
    return chamfer(body, p.face_chamfer, edges) if p.face_chamfer > 0 else body


def make_pinion_solid(p, L):
    """Gear in XY (axis Z), sector on +X; then turned so its axis is world Y, centred on the frame plane."""
    from bd_warehouse.gear import SpurGear
    g = SpurGear(p.module, p.teeth, p.pressure_angle, p.pinion_t, addendum=p.pinion_addendum,
                 dedendum=L["ded_p"])
    a = p.sector_teeth * L["tau"] / 2
    R = L["ra"] + 2
    pts = [(0, 0)] + [(R * cos(-a + 2 * a * i / 24), R * sin(-a + 2 * a * i / 24)) for i in range(25)]
    keep = extrude(Polygon(*pts, align=None), p.pinion_t, both=True) + Cylinder(L["rf"], 2 * p.pinion_t)
    g = g & keep
    # to the assembly frame: gear +Y -> world +Z, gear Z -> world -Y, centred at y_pc
    g = Pos(0, L["y_pc"], 0) * Rot(90, 0, 0) * g
    bore = xz(tri_flat_off(p.shaft_r, p.shaft_zf, L["sn"]), L["y_pf"] - 0.1, L["y_pb"] + 0.1)
    return g - bore


def make_base(p, L):
    zg, bh = L["zg"], p.base_h
    bx, y0, y1 = L["bx"], L["by0"], L["by1"]
    base = Pos(0, (y0 + y1) / 2, 0) * extrude(RectangleRounded(2 * bx, y1 - y0, p.base_r), bh)
    # pillar: plain prism, 45-deg shoulders to a flat top
    hw = p.pillar_w / 2
    top = zg + hw
    pil = Polygon((-hw, bh - 0.01), (hw, bh - 0.01), (hw, top - hw / 2), (hw / 2, top), (-hw / 2, top),
                  (-hw, top - hw / 2), align=None)
    base += xz(pil, L["y_p0"], L["y_p1"])
    # screen: a plain plate on the pillar front, wide enough to cover the crank's sweep and low enough
    # to hide behind the frame's top bar, so the crank never shows through the window from the front
    sw = p.crank_r + p.knob_r + 1.0
    st = zg + L["R_in"] + 1.5          # just over the window's top edge: the top bar hides the rest, even from above
    scr = Pos(0, (bh + st) / 2 - 0.005) * Rectangle(2 * sw, st - bh + 0.01)
    base += xz(scr, L["y_p0"], L["y_p0"] + p.screen_t)
    br = p.boss_r
    boss = Pos(0, zg) * Circle(br) + Polygon((-br * 0.7071, zg - br * 0.7071), (0, zg - br * 1.4142),
                                             (br * 0.7071, zg - br * 0.7071), (0, zg), align=None)
    base += xz(boss, L["y_boss"], L["y_p0"] + 0.01)
    base -= xz(bearing_hole(p.shaft_r + L["lo"], 0, zg), L["y_boss"] - 0.1, L["y_p1"] + 0.1)
    # post sockets: slot through the plinth for the prongs, pocket underneath for the hooks
    # (its roof = the catch ledge, short bridges along X anchored at both ends)
    sn = L["sn"]
    yc = L["y_pc"]
    for s in (-1, 1):
        xc = s * (L["x_pi"] + L["x_po"]) / 2
        base -= Pos(xc, yc, (L["z_ledge"] + bh) / 2) * Box(p.post_t + 2 * sn, 2 * (L["pr1"] + sn), bh - L["z_ledge"] + 0.2)
        wp = L["pr1"] + p.snap_e + 0.4
        base -= Pos(xc, yc, L["z_ledge"] / 2 - 0.05) * Box(p.post_t + 2 * sn, 2 * wp, L["z_ledge"] + 0.1)
    # raised '114' on the front strip
    yl = (y0 + L["y_ff"]) / 2
    txt = Pos(0, yl, bh - 0.01) * extrude(Text("114", p.label_h / CAP, **TXT), p.label_proud + 0.01)
    return base + txt


def make_post(p, L, side):
    """Plain prism: (y, z) profile extruded along X (printed on its side, so every feature is a 2D profile).
    Two snap prongs hang inside the post between slits and drop through the plinth; their hooks catch the
    ledge under it. The outer walls carry the post on the plinth top. Prongs bend in-layer."""
    sl, zg, sn = L["sl"], L["zg"], L["sn"]
    yc, pw = L["y_pc"], L["pw"]
    zt, bh = L["post_top"], p.base_h
    prof = Pos(yc, (bh + zt) / 2) * RectangleRounded(2 * pw, zt - bh, p.post_r)
    prof -= Pos(L["y_pc"], zg) * Rectangle(p.frame_t + 2 * sl, p.rod_w + 2 * sl)
    zr = p.prong_top
    for y0, y1 in ((-L["pr0"], L["pr0"]), (L["pr1"], L["pr1"] + p.prong_gap), (-L["pr1"] - p.prong_gap, -L["pr1"])):
        w = y1 - y0
        prof -= Pos(yc + (y0 + y1) / 2, (bh - 1 + zr - w / 2) / 2) * Rectangle(w, zr - w / 2 - bh + 1)
        prof -= Pos(yc + (y0 + y1) / 2, zr - w / 2) * Circle(w / 2)       # round slot tops = prong root fillets
    e, zc = p.snap_e, L["z_catch"]
    for s_ in (-1, 1):
        a0, a1 = L["pr0"], L["pr1"]
        prong = Pos(yc + s_ * (a0 + a1) / 2, (L["z_tip"] + bh + 0.5) / 2) * Rectangle(a1 - a0, bh + 0.5 - L["z_tip"])
        pts = [(s_ * (a1 - 0.05), zc), (s_ * (a1 + e), zc), (s_ * (a1 + e), zc - p.hook_land),
               (s_ * (a1 - 0.05), zc - p.hook_land - L["ramp_h"])]
        hook = Polygon(*(pts if s_ < 0 else pts[::-1]), align=None)      # same winding both sides, so it fuses
        prof += prong + Pos(yc, 0) * hook
    # seam notch: sharp V on the back (+Y) face, between the prong roots and the rod hole, so the
    # slicer's aligned seam sits here instead of on the snap roots
    zn = (p.prong_top + zg - p.rod_w / 2 - sl) / 2
    n, h = p.seam_notch, p.seam_notch * tan(radians(30))       # 60-deg V: sharper than any root, so it wins
    prof -= Polygon((yc + pw + 0.01, zn - h - 0.01), (yc + pw - n, zn), (yc + pw + 0.01, zn + h + 0.01), align=None)
    x0, x1 = (L["x_pi"], L["x_po"]) if side > 0 else (-L["x_po"], -L["x_pi"])
    post = yz(prof, x0, x1)
    return post


def knob_profile(p, R, zf):
    """Flat-topped octagonal knob section on the shared bed flat: vertical sides from the plate,
    45-deg facets to a flat top (no curved up-facing surface)."""
    k = p.knob_r
    c = k * tan(radians(22.5))
    return Polygon((R - k, -zf), (R + k, -zf), (R + k, c), (R + c, k), (R - c, k), (R - k, c), align=None)


def make_crank(p, L):
    """Shaft frame: axis along Y through the origin, bed flat at z = -shaft_zf. Arm along +X, behind the pillar."""
    r, zf = p.shaft_r, p.shaft_zf
    sp = tri_flat(r, zf)
    if p.shaft_corner_r > 0:
        sp = fillet2d(sp, p.shaft_corner_r, [v for v in sp.vertices() if v.Y > 0])   # upper D corners only
    shaft = xz(sp, L["y_shaft"], L["y_arm"] + 0.5)
    hub = xz(tri_flat(p.hub_r, zf), L["y_hub"], L["y_arm"] + 0.5)
    R = p.crank_r
    arm = tri_flat(p.hub_r, zf) + knob_profile(p, R, zf)
    arm += Polygon((0, -zf), (R, -zf), (R, p.arm_h - 0.4), (0, p.arm_h), align=None)
    arm = xz(arm, L["y_arm"], L["y_armb"])
    knob = xz(knob_profile(p, R, zf), L["y_armb"] - 0.5, L["y_knob"])
    c = (shaft + hub + arm + knob).clean()
    # shaft snap: slit (round root) beside a flexing prong on +X, barb on its side flat; bends in-layer
    a = sqrt(r * r - zf * zf)
    xs1 = a - p.shaft_prong                    # prong inner face at the root
    xs0 = xs1 - p.shaft_slit                   # rigid half's face
    w = p.shaft_slit
    yr, yc_ = L["y_root"], L["y_catch"]
    xt = a - p.shaft_prong_tip                 # prong inner face at the barb (taper halves the strain peak)
    slit = Polygon((xs0, yr - w / 2), (xs1, yr - w / 2), (xt, yc_), (xt, L["y_shaft"] - 1),
                   (xs0, L["y_shaft"] - 1), align=None)
    slit += Pos(xs0 + w / 2, yr - w / 2) * Circle(w / 2)
    c -= Pos(0, 0, -zf - 1) * extrude(slit, 2 * r + 2, dir=(0, 0, 1))
    e = p.snap_e
    barb = Polygon((a - 0.01, yc_), (a + e, yc_), (a + e, yc_ - p.barb_land), (a - 0.01, yc_ - p.barb_land - e), align=None)
    c += Pos(0, 0, -zf) * extrude(barb, 2 * zf, dir=(0, 0, 1))
    # concave root fillets (peak stress) at the shaft/hub shoulder and where the hub meets the arm;
    # never on the shared bed flat
    def ring_edges(y, rin):
        """Concave edges where a D-section of radius rin (flats at the shared bed plane) meets a face at y."""
        ain = sqrt(rin * rin - zf * zf)
        out = []
        for e in c.edges().filter_by(lambda e: abs(e.center().Y - y) < 0.01 and e.center().Z > -zf + 0.3):
            if e.geom_type == GeomType.LINE and abs(abs(e.center().X) - ain) < 0.02:
                out.append(e)
            elif e.geom_type == GeomType.CIRCLE and abs(e.radius - rin) < 0.02:
                out.append(e)
        return out
    # The shaft/hub shoulder can't take a fillet: it would run into the pillar bearing (0.3 mm gap), and OCC
    # can't fillet a D-section chain that ends on the shared bed plane. At the hub/arm junction the
    # vertical concave edges (hub side flat against the arm bar) do take one: that's where the peak sits.
    # Built as a prism (top-view quarter round over the flat's height) rather than an OCC fillet, which
    # only managed 0.5 mm and left a mesh that inverted at the 0.65x refinement.
    ah, rr = sqrt(p.hub_r ** 2 - zf ** 2), p.root_r
    ya = L["y_arm"]
    q = Pos(ah + rr / 2 - 0.01, ya - rr / 2 + 0.01) * Rectangle(rr + 0.02, rr + 0.02) - Pos(ah + rr, ya - rr) * Circle(rr)
    c = c + Pos(0, 0, -zf) * extrude(q, 2 * zf, dir=(0, 0, 1))
    # seam notch: sharp V on the arm's back face, half-way out, so the aligned seam leaves the root fillet
    n, xn, yb = p.seam_notch, p.crank_r / 2, L["y_armb"]
    h = n * tan(radians(30))
    v = Polygon((xn - h - 0.01, yb + 0.01), (xn, yb - n), (xn + h + 0.01, yb + 0.01), align=None)
    c = c - Pos(0, 0, -zf - 0.1) * extrude(v, zf + p.arm_h + 0.2, dir=(0, 0, 1))
    return c.clean()


def make_cap(p, L):
    """Front hub: the shaft's split end snaps through it; the barb catches on the counterbore floor, where
    the cut shaft end shows at the hub centre (the engraving's hatched shaft). Printed front face up."""
    y0, y1 = L["y_cf"], L["y_pf"]
    c = xz(Circle(p.cap_r), y0, y1)
    c -= xz(tri_flat_off(p.shaft_r, p.shaft_zf, L["sn"]), y0 - 0.1, y1 + 0.1)
    a = sqrt(p.shaft_r ** 2 - p.shaft_zf ** 2)
    rcb = sqrt((a + p.snap_e) ** 2 + p.shaft_zf ** 2) + p.cap_cb_clear   # clears the barb's corners
    c -= xz(Circle(rcb), y0 - 0.1, L["y_cb"])
    return c


# ---------------------------------------------------------------- build
def _shapes(p, L):
    import hashlib
    import sys
    from pathlib import Path
    cache = sys.__dict__.setdefault("_forge_mutpinion_cache", {})
    key = hashlib.sha256(Path(__file__).read_bytes() + repr(sorted(
        (k, v) for k, v in vars(p).items() if k != "crank_deg")).encode()).hexdigest()
    if key not in cache:
        cache.clear()
        cache[key] = dict(base=make_base(p, L), frame=make_frame(p, L), pinion=make_pinion_solid(p, L),
                          post_l=make_post(p, L, -1), post_r=make_post(p, L, 1),
                          crank=make_crank(p, L), cap=make_cap(p, L))
    return cache[key]


def build(p) -> Design:
    L = layout(p)
    S = _shapes(p, L)
    zg = L["zg"]
    th = p.crank_deg
    x = frame_x(p, L, th)
    rot = ((0, 0, zg), (0, -th, 0))        # CCW seen from the front (-Y)
    parts = [
        Part("base", S["base"], color="#4A4F55", orient=(0, 0, 0), cosmetic=["+z", "-y"],
             notes="Plinth with the pinion pillar (45-deg roof bearing, thrust boss), two snap sockets (slot + underside pocket whose roof is the catch ledge), raised '114'."),
        Part("frame", S["frame"], color="#B08D57", placement=(x, 0, zg), orient=(-90, 0, 0), cosmetic=["-y"],
             notes="Stadium frame + flared end rods + both racks, printed flat on its back, front face up."),
        Part("pinion", S["pinion"], color="#C9A24A", placement=rot, orient=(-90, 0, 0), cosmetic=["-y"],
             notes=f"Mutilated pinion: {p.sector_teeth} of {p.teeth} teeth, m{p.module}, printed back face down; keyed on the shaft flats."),
        Part("post_l", S["post_l"], color="#4A4F55", orient=(0, 90, 0), cosmetic=["-y"],
             notes="Left bearing post: prism printed on its side (square rod hole vertical); two in-layer snap prongs hook under the plinth."),
        Part("post_r", S["post_r"], color="#4A4F55", orient=(0, -90, 0), cosmetic=["-y"],
             notes="Right bearing post (mirror of the left)."),
        Part("crank", S["crank"], color="#3E4349", placement=rot, orient=(0, 0, 0),
             notes="Shaft + hub + arm + knob behind the pillar, printed lying on the shared bottom flat."),
        Part("cap", S["cap"], color="#C9A24A", placement=rot, orient=(-90, 0, 0), cosmetic=["-y"],
             notes="Front hub: the split shaft end snaps through it (barb on the counterbore floor); printed front face up."),
    ]
    yc = L["y_pc"]
    fits = [
        Fit("pinion", "frame", "sliding", retention="captured", drives=True,
            region=Region((-L["ra"] - 2, L["y_ff"] - 0.5, zg - L["ra"] - 2), (L["ra"] + 2, L["y_fb"] + 0.5, zg + L["ra"] + 2)),
            notes="Rack mesh: normal flank gap 0.22 mm at every engaged pose (racks thinned)."),
        Fit("frame", "post_l", "sliding", retention="captured",
            region=Region((-L["x_po"] - 0.5, -20, zg - 10), (-L["x_pi"] + 0.5, 20, zg + 10)),
            notes="Square rod in the left post; the frame is captured by its rods in both posts."),
        Fit("frame", "post_r", "sliding", retention="captured",
            region=Region((L["x_pi"] - 0.5, -20, zg - 10), (L["x_po"] + 0.5, 20, zg + 10)),
            notes="Square rod in the right post."),
        Fit("post_l", "base", "snug", retention="snap", snap_case="post_snap",
            region=Region((-L["x_po"] - 1, -20, -0.1), (-L["x_pi"] + 1, 20, p.base_h - 0.05)),
            notes="Prongs in the slot, hooks under the ledge; outer walls rest on the plinth top."),
        Fit("post_r", "base", "snug", retention="snap", snap_case="post_snap",
            region=Region((L["x_pi"] - 1, -20, -0.1), (L["x_po"] + 1, 20, p.base_h - 0.05)),
            notes="Mirror of the left post (same snap)."),
        Fit("pinion", "crank", "snug", retention="captured", notes="Keyed on the tri-flat shaft, held between the boss and the hub cap."),
        Fit("pinion", "base", "loose", retention="captured", notes="Pinion back face runs on the pillar's thrust boss."),
        Fit("crank", "base", "loose", retention="captured",
            notes="Shaft in the pillar bearing: hub thrust on the pillar back, pinion + snapped cap in front."),
        Fit("cap", "crank", "snug", retention="snap", snap_case="cap_snap",
            notes="Split shaft end through the cap; barb catches the counterbore floor."),
        Fit("cap", "pinion", "contact", retention="captured", notes="Cap holds the pinion against the boss."),
    ]
    return Design(
        parts=parts, fits=fits, loads=loads(p, L),
        explode={"frame": (0, -25, 0), "pinion": (0, -45, 0), "cap": (0, -60, 0), "crank": (0, 40, 0),
                 "post_l": (-15, 0, 20), "post_r": (15, 0, 20)},
        motion=Motion("crank_deg", 0, 360, 10, min_travel_mm=15,
                      exclude_travel=("pinion", "crank", "cap")),
    )


def loads(p, L):
    R, zf = p.crank_r, p.shaft_zf
    jr = p.shaft_r + 0.5
    e, sn = p.snap_e, L["sn"]
    a = sqrt(p.shaft_r ** 2 - zf ** 2)
    yc, zc = L["y_pc"], L["z_catch"]
    ya = yc + L["pr1"] + e                      # +Y hook apex
    return [
        LoadCase("crank_push", part="crank",
                 fixed=Region((-jr, L["y_p0"], -jr), (jr, L["y_p1"] - 1.0, jr)),
                 load=Region((R - p.knob_r - 0.1, L["y_knob"] - p.knob_l / 2, -zf - 0.1),
                             (R + p.knob_r + 0.1, L["y_knob"] + 0.1, p.knob_r + 0.1)),
                 force=(0, 0, -10), use="static", mesh_size=0.5,
                 refine=Region((-p.hub_r - 1, L["y_p0"] - 1, -p.knob_r - 1), (R + p.knob_r + 1, L["y_knob"] + 1, p.knob_r + 1)),
                 notes="10 N tangential push on the outer half of the knob. Journal fixed, stopping 1 mm inside the pillar back: a clamp edge at the shoulder is an artificial singularity, and the longer arm is conservative."),
        LoadCase("post_snap", part="post_r",
                 fixed=Region((L["x_pi"] - 0.1, yc - L["pw"] - 0.1, p.prong_top + 1.0), (L["x_po"] + 0.1, yc + L["pw"] + 0.1, p.prong_top + 2.5)),
                 load=Region((L["x_pi"] - 0.1, ya - 0.05, zc - p.hook_land - 0.01), (L["x_po"] + 0.1, ya + 0.05, zc + 0.01)),
                 displacement=(0, -(e + sn), 0), nonlinear=True, use="repeated", min_force_n=5, max_force_n=15, steps=20,
                 mesh_size=0.4, refine=[Region((L["x_pi"] - 0.5, yc + L["pr0"] - 0.5, p.prong_top - 3), (L["x_po"] + 0.5, yc + L["pr1"] + p.prong_gap + 0.5, p.prong_top + 2.5)),
                                         Region((L["x_pi"] - 0.5, yc + L["pr0"] - 0.5, L["z_tip"] - 0.3), (L["x_po"] + 0.5, ya + 0.5, p.base_h + 0.5))],
                 notes="Slot edge on the +Y hook apex (a line along X) as the post goes in; post body above the prong roots fixed. "
                       "Displacement = engagement + gap. Two prongs per post with a 30-deg lead-in: push ~ 2 x 1.06 x this (forge flex)."),
        LoadCase("cap_snap", part="crank",
                 fixed=Region((-jr, L["y_root"] + 0.5, -jr), (jr, L["y_p0"] + 2, jr)),
                 load=Region((a + e - 0.05, L["y_catch"] - p.barb_land + 0.05, -zf - 0.1), (a + e + 0.05, L["y_catch"] - 0.05, zf + 0.1)),
                 displacement=(-(e + sn), 0, 0), nonlinear=True, use="repeated", min_force_n=5, max_force_n=15,
                 mesh_size=0.35, refine=Region((-jr, L["y_shaft"] - 0.5, -jr), (a + e + 0.5, L["y_root"] + 1, jr)),
                 notes="Cap hole edge on the barb apex (a line along Z) as the cap goes on; shaft behind the slit root fixed."),
    ]
