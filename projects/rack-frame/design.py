"""Double Rack-Frame (Brown 1868, movement 84), v3: built from mechanism.md. Every dimension is p.<param>.

What each part does (mechanism.md §1)
  B  stadium frame + raised slotted bar + END RODS (one part). Free in X (the output). Its rods ride in
     open-top vertical U bearings on two fixed posts (Y held, Z free by the selector stroke); its Z is
     SET by A's two pins (24 mm apart, so B cannot rock).
  A  rod + inverted-U fork + two pins in B's slot. Free in Z (3 detented positions), guided by a closed
     sleeve on the pedestal. Two symmetric in-layer flags inside the sleeve make the detent.
  D  4-blade cam + disc on a shaft in the pedestal. The blade/rack geometry and B's x(crank) are the
     2D push-only contact solve from study_2d.py (cam_shape reused), not invented here.
  UP      B raised:  the BOTTOM rack meets the blades -> B steps +X, one 6 mm tooth per blade, then pauses.
  DOWN    B lowered: the TOP rack (the bottom rack turned 180 deg) -> B steps -X.
  NEUTRAL the tip circle clears both tooth tip lines by neutral_clear.
  Each rack has exactly 2*travel_steps steep faces, so the cam runs off the last tooth at +-T.

Assembly (snap-together, no glue/screws)
  1. Push A up through the pedestal sleeve (grip first; the flags click into the notches).
  2. Crank shaft through the pedestal from behind; snap D onto its split tip (felt click).
  3. Drop B's rods into the posts' U bearings on the base.
  4. Slide the pedestal sub-assembly forward along the plinth dovetail: D's cam enters B's window,
     A's pins enter B's slot. The sill latch clicks into the plinth pocket.
  B is then held by the U cheeks (Y) and A's pins (Z); A by the sleeve and by B's bar in front of its fork.

Frames: desk z = 0, front is -Y, D's axis along Y at x = 0, z = axis_h. Parts are modelled at NEUTRAL
with B centred; B and A are modelled about z = 0 (the axis height) and placed at axis_h + dz.
"""
import hashlib
import importlib.util
import sys
from math import cos, degrees, pi, radians, sin, sqrt, tan
from pathlib import Path

from build123d import *

from forge.config import fits_table
from forge.dsl import Design, Fit, LoadCase, Motion, Part, Region

HERE = Path(__file__).resolve().parent
TXT = dict(font_style=FontStyle.BOLD)
CAP = 0.715          # cap height / font size for the bold default font


def _study():
    spec = importlib.util.spec_from_file_location("rackframe_study_2d", HERE / "study_2d.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- helpers (reused from v2)
def xz(face, y0, y1):
    """Extrude a sketch drawn in (x, z) between world y0 < y1."""
    return Rot(90, 0, 0) * Pos(0, 0, -y1) * extrude(face, y1 - y0, dir=(0, 0, 1))


def yz(face, x0, x1):
    """Extrude a (y, z) sketch along +X from x0 to x1."""
    return extrude(Plane.YZ.offset(x0) * face, x1 - x0, dir=(1, 0, 0))


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def tri_flat(r, zf, cx=0.0, cz=0.0):
    """Round printed lying on a flat at cz - zf, with vertical side flats where it meets the bed."""
    a = sqrt(r * r - zf * zf)
    top = r + 1
    return Pos(cx, cz) * Circle(r) & Pos(cx, cz + (top - zf) / 2) * Rectangle(2 * a, top + zf)


def bar_sec(a, zb, zt, c, cx=0.0, cz=0.0):
    """Lying bar section: flat bottom at -zb, vertical sides, 45-deg chamfers to a flat top at zt."""
    return Pos(cx, cz) * Polygon((-a, -zb), (a, -zb), (a, zt - c), (a - c, zt), (-a + c, zt), (-a, zt - c), align=None)


def text_face(txt, size, min_dot=0.85):
    out = None
    for f in Text(txt, size, **TXT).faces():
        if f.area < 1.6:
            c = f.center()
            f = Pos(c.X, c.Y) * Circle(min_dot)
        out = f if out is None else out + f
    return out


def glyph_D(h, stroke):
    def shape(x0, y0, x1, y1):
        hh = (y1 - y0) / 2
        c = x1 - hh
        return (Pos((x0 + c) / 2, y0 + hh) * Rectangle(c - x0, 2 * hh)
                + (Pos(c, y0 + hh) * Circle(hh) & Pos(c + hh / 2, y0 + hh) * Rectangle(hh, 2 * hh)))
    w = 0.8 * h
    hi = h - 2 * stroke
    ci = w - stroke - hi * 0.6
    counter = (Pos((stroke + ci) / 2, h / 2) * Rectangle(ci - stroke, hi)
               + (Pos(ci, h / 2) * Circle(hi * 0.6) & Pos(ci + hi * 0.3, h / 2) * Rectangle(hi * 0.6, hi)))
    return Pos(-w / 2, -h / 2) * (shape(0, 0, w, h) - counter)


def _try(fn, shape):
    try:
        out = fn(shape)
        ok = out is not None and out.is_valid and abs(out.volume - shape.volume) < 0.05 * shape.volume
        return out if ok else shape
    except Exception:
        return shape


def fillet(shape, r, edges):
    return _try(lambda s: s.fillet(r, edges), shape) if edges else shape


def fillet_each(shape, r, pick, tries=24):
    """Fillet edges one at a time (OCC often refuses a batch); `pick(shape)` returns candidate edges."""
    for _ in range(tries):
        done = False
        for e in pick(shape):
            s2 = _try(lambda s: s.fillet(r, [e]), shape)
            if s2 is not shape and len(s2.edges()) != len(shape.edges()):
                shape, done = s2, True
                break
        if not done:
            break
    return shape


def poly(coords):
    """build123d face from a shapely-style coordinate ring (CCW so extrusions go the right way)."""
    pts = [(float(x), float(y)) for x, y in coords]
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    area2 = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    if area2 < 0:
        pts = pts[::-1]
    return Polygon(*pts, align=None)


# ---------------------------------------------------------------- drive: 2D geometry + contact solve
def drive(p):
    """Cam and rack polygons (shapely, frame coords at NEUTRAL) and B's x per crank angle, per state."""
    import numpy as np
    from shapely import affinity
    from shapely.geometry import Point, Polygon as SP
    from shapely.ops import unary_union
    st = _study()
    R, c, d, h, P = p.cam_r, p.neutral_clear, p.engage_d, p.tooth_h, p.pitch
    g = dict(R=R)
    g["zt"] = R + c                     # neutral tooth tip line |z|
    g["Ri"] = R + c + h                 # tooth root line |z| = window half-height
    g["S"] = (R + c) - (R - d)          # selector stroke
    g["T"] = p.travel_steps * P
    cam = unary_union([st.cam_shape(R, p.blade_t, hub_r=p.blade_hub, sweep=p.blade_sweep),
                       Point(0, 0).buffer(p.cam_hub_r, 64)]).simplify(0.005)
    g["cam"] = cam
    zt, zr = -g["zt"], -g["Ri"]

    def teeth(faces, cut_first=False):
        out = []
        for i, f in enumerate(faces):
            end = f + p.tooth_flat + h if (cut_first and i == 0) else f + P - 0.05   # first tooth: 45-deg back
            out.append(SP([(f, zr - 0.6), (f, zt), (f + p.tooth_flat, zt), (end, zr), (end, zr - 0.6)]))
        return out

    def solve(rack, x0, sgn, phi0, n=721, step=0.5):
        xs, x = [], x0
        for i in range(n):
            G = affinity.rotate(cam, phi0 + i * step, origin=(0, 0))      # CCW from the front
            rk = affinity.translate(rack, x, 0)
            if G.intersects(rk) and G.intersection(rk).area > 1e-8:
                k = 0
                while G.intersection(affinity.translate(rack, x, 0)).area > 1e-8 and k < 3000:
                    x += sgn * 0.01
                    k += 1
                x += sgn * p.push_gap
            xs.append(x)
        return np.array(xs)

    S, T = g["S"], g["T"]
    # u_end: where a pushed steep face comes to rest (unbounded rack, same solver)
    inf = affinity.translate(unary_union(teeth([P * k for k in range(-15, 16)])), 0, S)
    xi = solve(inf, 0.0, +1, 0.0, n=1441)
    still = np.flatnonzero(np.abs(np.diff(xi)) < 1e-9)       # dwell samples; the last dwell is the steady rest
    g["u_end"] = float(xi[still[-1]] % P)
    # finite bottom rack: exactly 2 * travel_steps faces, so B goes -T -> +T and the cam runs off the last one
    faces = [g["u_end"] - P + T - P * k for k in range(2 * p.travel_steps)]
    g["faces"] = faces
    bot = teeth(faces, cut_first=True)
    top = [affinity.rotate(t, 180, origin=(0, 0)) for t in bot]
    g["bot"], g["top"] = bot, top
    rb = affinity.translate(unary_union(bot), 0, S)       # UP: B raised by S
    rt = affinity.translate(unary_union(top), 0, -S)      # DOWN: B lowered by S
    # start phase: a blade 10 deg before it touches the first face (B pauses, then steps)
    ov = [affinity.rotate(cam, a, origin=(0, 0)).intersection(affinity.translate(rb, -T, 0)).area > 1e-8
          for a in np.arange(0, 180, 0.5)]
    i0 = next(i for i in range(21, len(ov)) if ov[i] and not any(ov[i - 20:i]))
    g["phi0"] = (i0 - 20) * 0.5
    g["up_x"] = solve(rb, -T, +1, g["phi0"])
    g["dn_x"] = solve(rt, float(g["up_x"][-1]), -1, g["phi0"])
    g["runoff_x"] = float(solve(rb, -T, +1, g["phi0"], n=1441)[-1])      # 2 turns in UP: must stop at +T
    mv = np.diff(g["up_x"]) > 1e-9
    runs, cur = [], 0.0
    for dxv, m in zip(np.diff(g["up_x"]), mv):
        if m:
            cur += dxv
        elif cur:
            runs.append(cur)
            cur = 0.0
    g["up_steps"] = [round(r, 2) for r in runs + ([cur] if cur else []) if r > 0.5]
    rn = unary_union(bot + top)
    g["neutral_gap"] = min(affinity.rotate(cam, a, origin=(0, 0)).distance(affinity.translate(rn, float(g["dn_x"][-1]), 0))
                           for a in range(0, 360, 3))
    return g


# ---------------------------------------------------------------- layout
def layout(p):
    ft = fits_table()
    L = dict(sn=ft["snug"]["gap"], sl=ft["sliding"]["gap"], lo=ft["loose"]["gap"])
    g = drive(p)
    L.update(g)
    sl, lo, S, T = L["sl"], L["lo"], g["S"], g["T"]
    zg = p.axis_h
    L["zg"] = zg
    # ---- Y stack (front is -Y)
    L["yBf"], L["yBb"] = -p.frame_t, 0.0
    L["yA0"], L["yA1"] = sl, sl + p.sel_t
    L["yd0"] = L["yA1"] + p.disc_gap
    L["yd1"] = L["yd0"] + p.disc_t
    L["yp0"] = L["yd1"] + lo
    L["yp1"] = L["yp0"] + p.ped_d
    L["ycf"] = L["yBf"] + p.cam_set
    L["y_sh"] = L["yd1"] + 0.1
    L["y_tip"] = L["ycf"] + p.bore_skin + 0.1
    L["y_h0"] = L["yp1"] + lo + 0.8
    L["y_arm0"] = L["y_h0"] + 1.0
    L["y_arm1"] = L["y_arm0"] + p.crank_t
    L["y_knob"] = L["y_arm1"] + p.knob_l
    # ---- frame B (relative to its centre)
    L["Ro"] = g["Ri"] + p.rim_t
    L["F"] = p.frame_ls + L["Ro"]                       # frame half-length
    L["slot_h"] = p.pin_d + 2 * sl
    L["z_slot0"] = L["Ro"] + p.bar_rail
    L["z_pin"] = L["z_slot0"] + L["slot_h"] / 2
    L["z_bar"] = L["z_slot0"] + L["slot_h"] + p.bar_rail
    L["slot_cc"] = p.pin_s + 2 * (T + p.hand_gap + p.pin_overrun)
    L["bar_x"] = L["slot_cc"] / 2 + L["slot_h"] / 2 + p.bar_end
    L["x_stop"] = T + p.hand_gap                        # hand stop: B's end on the post's front cheek
    L["x_pi"] = L["F"] + L["x_stop"]                    # post inner face |x|
    L["x_po"] = L["x_pi"] + p.post_t
    L["Lr"] = 2 * L["x_stop"] + p.post_t + p.rod_past   # rod length beyond the frame end
    L["x_rod"] = L["F"] + L["Lr"]                       # rod end |u|
    L["swept_w"] = 2 * (L["x_rod"] + T)
    L["web_x"] = L["x_stop"] + p.cam_r + p.web_clear    # web edge |u| (clear of the cam at the hand stop)
    # ---- posts (absolute z)
    L["y_sl0"], L["y_sl1"] = -p.rod_t - sl, sl          # U slot (Y)
    L["z_floor"] = zg - p.rod_h / 2 - S - p.floor_cl
    L["z_cheek"] = zg + p.rod_h / 2 + S + p.stop_cl + p.cheek_top
    # ---- selector A (relative to the axis, at NEUTRAL)
    L["z_leg0"] = L["z_pin"] - p.pin_d / 2 - p.leg_below
    L["z_cr0"] = L["z_bar"] + p.crown_cl
    L["z_ct"] = L["z_cr0"] + p.crown_h
    L["fx"] = p.pin_s / 2 + p.leg_w / 2                 # fork outer half-width
    L["x_fl0"] = p.core_w / 2 + p.flag_gap              # flag inner face
    L["x_fl1"] = L["x_fl0"] + p.flag_t                  # flag outer face
    L["x_si"] = L["x_fl1"] + sl                         # sleeve inner half-width
    L["x_so"] = L["x_si"] + p.sleeve_wall
    L["z_s0"] = L["z_ct"] + S + p.stop_cl               # sleeve bottom: A's crown hits it just past UP
    L["z_ftip"] = L["z_ct"] + p.flag_l
    L["z_b"] = L["z_ftip"] - p.bump_h - 0.2             # bump centre (A at NEUTRAL)
    L["z_s1"] = L["z_ftip"] + S + 1.4                   # sleeve top
    L["z_g0"] = L["z_s1"] + S + p.stop_cl               # grip bottom
    L["z_g1"] = L["z_g0"] + p.grip_h
    # ---- pedestal / plinth (absolute)
    L["z_sill1"] = p.plinth_h + p.sill_h
    L["x_lr"] = p.rail_w / 2 + p.rail_h + 1.5            # latch root |x| (clear of the dovetail groove)
    L["x_lt"] = L["x_lr"] + p.latch_l
    L["y_pl0"] = L["yBf"] - p.plinth_front + p.frame_t
    L["y_pl1"] = L["yp1"] + 0.2 + p.pocket_wall
    return L


# ---------------------------------------------------------------- parts
def stadium(Ls, R):
    return Rectangle(2 * Ls, 2 * R) + Pos(-Ls, 0) * Circle(R) + Pos(Ls, 0) * Circle(R)


def make_frame(p, L):
    Ls, Ri, Ro, F = p.frame_ls, L["Ri"], L["Ro"], L["F"]
    bx = L["bar_x"]
    from shapely.geometry import Point as SPt, LineString as SLs, box as sbox
    outline = SLs([(-Ls, 0), (Ls, 0)]).buffer(Ro, 64)                                    # stadium
    outline = outline.union(SLs([(-L["slot_cc"] / 2, L["z_pin"]), (L["slot_cc"] / 2, L["z_pin"])]).buffer(L["slot_h"] / 2 + p.bar_rail, 64))
    xs = bx - p.bar_step                                                                   # stepped shoulder under each bar end
    outline = outline.union(sbox(-xs, 0, xs, L["z_pin"]))
    outline = outline.buffer(p.bar_fillet, 32).buffer(-p.bar_fillet, 32).simplify(0.02)   # concave fillets only
    face = poly(outline.exterior.coords)
    face -= stadium(Ls, Ri)
    for t in L["bot"] + L["top"]:
        face += poly(t.exterior.coords)
    face -= Pos(0, L["z_pin"]) * SlotCenterToCenter(L["slot_cc"], L["slot_h"])
    gw, gh = p.fin_w + 2 * p.fin_cl, p.fin_h + p.fin_cl                      # relief groove for the pins' seam fins
    face -= Pos(0, L["z_pin"] + L["slot_h"] / 2 + gh / 2 - 0.3) * Rectangle(L["slot_cc"] + gw, gh + 0.6)
    body = xz(face, L["yBf"], L["yBb"])
    # end rods (part of B), lying in the print plane
    for s in (-1, 1):
        x0, x1 = sorted((s * (F - 2.0), s * L["x_rod"]))
        body += box(x0, x1, -p.rod_t, 0.0, -p.rod_h / 2, p.rod_h / 2)
    # recessed web in the window's left end with a raised B (the engraving's B sits there)
    wx = L["web_x"]
    web = (Pos(-Ls, 0) * Circle(Ri + 0.01)) & Pos(-(wx + Ls + Ri) / 2, 0) * Rectangle(Ls + Ri - wx, 2 * Ri)
    body += xz(web, -p.web_t, 0.0)
    xb = -(wx + Ls + Ri - 2.5) / 2
    body += xz(Pos(xb, 0) * text_face("B", 6.0 / CAP), -p.web_t - p.letter_h, -p.web_t + 0.01)
    # round the convex footprint corners (edges normal to the print bed = along Y)
    pick = lambda b: b.edges().filter_by(Axis.Y).filter_by(
        lambda e: e.length > 3.5 and (abs(e.center().X) > L["x_rod"] - 0.1 or abs(abs(e.center().X) - bx) < 0.05))
    body = fillet_each(body, 0.8, pick)
    return body


def make_cam(p, L):
    """D + its disc in one part, printed disc-down; blades run back to the disc (no overhang)."""
    face = poly(L["cam"].exterior.coords)
    cam = xz(face, L["ycf"], L["yd0"] + 0.01)
    cam += xz(Circle(p.disc_r), L["yd0"], L["yd1"])
    # each blade's curve continued into the disc face as a shallow groove out to the rim (reads as the engraving's wheel)
    import numpy as np
    from shapely.geometry import LineString as SLs
    from shapely.ops import unary_union
    rt = p.cam_r - p.blade_t / 2
    gr = []
    for k in range(4):
        c0 = pi / 2 * k + radians(p.blade_sweep)
        pts = [((rt + (p.disc_r + 1 - rt) * u) * sin(c0 + radians(p.groove_sweep) * u),
                -(rt + (p.disc_r + 1 - rt) * u) * cos(c0 + radians(p.groove_sweep) * u)) for u in np.linspace(0, 1, 40)]
        gr.append(SLs(pts).buffer(p.groove_w / 2, 8))
    grooves = unary_union(gr).difference(L["cam"].buffer(0.3))
    for gpoly in getattr(grooves, "geoms", [grooves]):
        cam -= xz(poly(gpoly.exterior.coords), L["yd0"] - 0.01, L["yd0"] + p.groove_d)
    yb = L["ycf"] + p.bore_skin
    th, zf, sn = p.tip_half, p.shaft_zf, L["sn"]
    cam -= xz(Rectangle(2 * (th + sn), 2 * (zf + sn)), yb, L["yd1"] + 0.1)
    cam -= xz(Rectangle(2 * (th + sn + 0.3), 2 * (zf + sn + 0.3)), L["yd1"] - 0.6, L["yd1"] + 0.1)   # elephant-foot relief
    # snap grooves for the shaft's barbs (catch face = the groove's +Y face, up-facing in print)
    yc = L["y_tip"] + p.barb_l + 0.1
    for sx in (-1, 1):
        x0, x1 = sorted((sx * (th + sn - 0.01), sx * (th + p.barb + 0.3)))
        cam -= box(x0, x1, yb - 0.01, yc, p.snap_z0 - L["sl"], p.snap_z1 + L["sl"])
    cam += xz(glyph_D(p.d_letter, 0.9), L["ycf"] - p.letter_h, L["ycf"] + 0.01)
    return cam


def make_selector(p, L):
    y0, y1 = L["yA0"], L["yA1"]
    fx, r = L["fx"], p.fork_r
    xi = p.pin_s / 2 - p.leg_w / 2                      # fork inner half-width
    zl, zc0, zct = L["z_leg0"], L["z_cr0"], L["z_ct"]
    fork = Pos(0, (zl + zct) / 2) * Rectangle(2 * fx, zct - zl) - Pos(0, (zl - 1 + zc0) / 2) * Rectangle(2 * xi, zc0 - zl + 1)
    A = xz(fork, y0, y1)
    # rod core through the sleeve, grip on top (grip passes up through the sleeve at assembly)
    A += xz(Pos(0, (zct - 0.5 + L["z_g0"]) / 2) * Rectangle(p.core_w, L["z_g0"] - zct + 0.5), y0, y1)
    A += xz(Pos(0, (L["z_g0"] + L["z_g1"]) / 2) * Rectangle(p.grip_w, p.grip_h), y0, y1)
    # detent flags: two in-layer cantilevers standing on the crown, bumps out into the sleeve walls
    for s in (-1, 1):
        xa, xb = sorted((s * L["x_fl0"], s * L["x_fl1"]))
        A += box(xa, xb, y0, y1, zct - 0.5, L["z_ftip"])
    A = A.clean()
    # round the fork's outer crown corners and its inner corners (all in the print plane)
    A = fillet_each(A, r, lambda a: a.edges().filter_by(Axis.Y).filter_by(
        lambda e: abs(abs(e.center().X) - fx) < 0.01 and abs(e.center().Z - zct) < 0.01))
    A = fillet_each(A, 1.2, lambda a: a.edges().filter_by(Axis.Y).filter_by(
        lambda e: abs(abs(e.center().X) - xi) < 0.01 and abs(e.center().Z - zc0) < 0.01))
    A = fillet_each(A, p.flag_root_r, lambda a: a.edges().filter_by(Axis.Y).filter_by(
        lambda e: abs(e.center().Z - zct) < 0.01 and (abs(abs(e.center().X) - L["x_fl0"]) < 0.01
                                                      or abs(abs(e.center().X) - L["x_fl1"]) < 0.01
                                                      or abs(abs(e.center().X) - p.core_w / 2) < 0.01)))
    # bumps: 45-deg flanks with a 0.2 flat
    hb, zb = p.bump_h, L["z_b"]
    for s in (-1, 1):
        x0 = s * (L["x_fl1"] - 0.05)
        x1 = s * (L["x_fl1"] + hb)
        bump = Polygon((x0, zb - hb - 0.1 - 0.05), (x1, zb - 0.1), (x1, zb + 0.1), (x0, zb + hb + 0.1 + 0.05), align=None)
        A += xz(bump, y0, y1)
    # pins (short stubs pointing forward through B's slot; upright in print, ~0.4 N service load)
    for xp in (-p.pin_s / 2, p.pin_s / 2):
        pin = Pos(xp, L["z_pin"]) * Circle(p.pin_d / 2)
        # seam catcher: the slicer's 'back' seam goes to the rearmost point (the pin top on the plate); a slim fin puts it in B's relief groove
        pin += Pos(xp, L["z_pin"] + (p.pin_d / 2 + p.fin_h) / 2) * Rectangle(p.fin_w, p.pin_d / 2 + p.fin_h)
        A += xz(pin, L["yBf"] + p.pin_set, y0 + 0.01)
    # drag tongue: in-layer leaf from the left leg, its nub rubs B's bar (A moves with B in Z, so only X slides)
    zt1 = L["z_cr0"] - 0.4                              # leaf top: clear of the crown (free cantilever)
    zt0 = zt1 - p.drag_b
    xr = -xi
    A += box(xr - 0.5, xr + p.drag_l, y1 - p.drag_t, y1, zt0, zt1)
    A = fillet_each(A, 0.8, lambda a: a.edges().filter_by(Axis.Y).filter_by(
        lambda e: abs(e.center().X - xr) < 0.01 and min(abs(e.center().Z - zt0), abs(e.center().Z - zt1)) < 0.01))
    zn = L["z_bar"] - p.bar_rail / 2
    xn = xr + p.drag_l - 1.2
    A += box(xn - 1.0, xn + 1.0, -p.drag_int, y1 - p.drag_t + 0.01, zn - 0.7, zn + 0.7)
    # A in relief on the grip: recessed panel with the letter flush (it passes through the sleeve)
    zg0, zg1 = L["z_g0"], L["z_g1"]
    pd = p.letter_h
    A -= xz(Pos(0, (zg0 + zg1) / 2) * Rectangle(p.grip_w - 2.0, p.grip_h - 1.6), y0 - 0.1, y0 + pd)
    A += xz(Pos(0, (zg0 + zg1) / 2) * text_face("A", (p.grip_h - 2.6) / CAP), y0, y0 + pd + 0.01)
    return A


def rail_ring(p, off, ph):
    """Dovetail rail section (x, z): a 0.4 mm vertical neck at the plinth, then 45-deg flanks (print unsupported).
    off > 0 gives the sill's groove (mitred offset, clipped below the plinth top)."""
    from shapely.geometry import Polygon as SP, box as sbox
    rw, rh, nk = p.rail_w / 2, p.rail_h, p.rail_neck
    r = SP([(-rw, ph - 1.0), (rw, ph - 1.0), (rw, ph + nk), (rw + rh - nk, ph + rh), (-(rw + rh - nk), ph + rh), (-rw, ph + nk)])
    if off:
        r = r.buffer(off, join_style=2)
    return r.intersection(sbox(-50, ph - (0.1 if off else 0.01), 50, ph + rh + 1))


def make_base(p, L):
    zg, ph = L["zg"], p.plinth_h
    W = 2 * (L["x_po"] + p.arm_off + 2.0)
    y0, y1 = L["y_pl0"], L["y_pl1"]
    base = Pos(0, (y0 + y1) / 2, 0) * extrude(RectangleRounded(W, y1 - y0, p.plinth_r), ph)
    ys0, ys1 = L["y_sl0"], L["y_sl1"]
    yc0, yc1 = ys0 - p.cheek_t, ys1 + p.cheek_t
    for s in (-1, 1):
        xa, xb = sorted((s * L["x_pi"], s * L["x_po"]))
        z_top, z_bot = L["z_floor"], ph - 0.01
        if s > 0:
            post = box(xa, xb, yc0, yc1, z_bot, z_top)
        else:   # the left post stands on a curved arm, as drawn
            n = 16
            xm = (xa + xb) / 2
            xc = lambda z: xm - p.arm_off * ((z_top - z) / (z_top - z_bot)) ** 2
            zs = [z_bot + (z_top - z_bot) * i / n for i in range(n + 1)]
            pts = [(xc(z) - p.post_t / 2, z) for z in zs] + [(xc(z) + p.post_t / 2, z) for z in reversed(zs)]
            post = xz(Polygon(*pts, align=None), yc0, yc1)
        post += box(xa, xb, yc0, ys0, z_top - 0.01, L["z_cheek"])      # front cheek
        post += box(xa, xb, ys1, yc1, z_top - 0.01, L["z_cheek"])      # back cheek
        base += post
    # dovetail rail for the pedestal sill (45-deg flanks print unsupported)
    rail = poly(rail_ring(p, 0.0, ph).exterior.coords)
    base += xz(rail, L["yp0"], L["yp1"] - p.groove_back)       # rail ends at the groove's blind back wall: forward stop
    # latch pocket (the sill's barb drops in; the pocket's back wall is the catch)
    base -= box(L["x_lt"] - p.barb_x0 - 0.3, L["x_lt"] - p.barb_x1 + 0.3, L["yp0"] - 0.2, L["yp1"] + 0.2, ph - p.latch_pocket, ph + 0.1)
    # 'No. 84' raised on the plinth front strip
    yc = (y0 + L["y_sl0"] - p.cheek_t) / 2
    base += Pos(0, yc, ph - 0.01) * extrude(text_face("No. 84", 4.2 / CAP), p.letter_h)
    return base


def make_pedestal(p, L):
    zg, ph = L["zg"], p.plinth_h
    yp0, yp1 = L["yp0"], L["yp1"]
    sx, zs1 = p.sill_x, L["z_sill1"]
    ux0, ux1 = p.upr_x - p.upr_w, p.upr_x
    # profile in (x, z), extruded over the pedestal depth (printed on its back, so all of this is in-plane)
    prof = Pos(0, (ph + zs1) / 2) * Rectangle(2 * sx, zs1 - ph)                         # sill
    for s in (-1, 1):
        prof += Pos(s * (ux0 + ux1) / 2, (zs1 - 0.5 + zg) / 2) * Rectangle(p.upr_w, zg - zs1 + 0.5)   # uprights
    prof += Pos(0, zg) * Rectangle(2 * p.upr_x, 2 * p.head_h)                           # bearing head
    zcol1 = zg + L["z_s1"]
    prof += Pos(0, (zg + zcol1) / 2) * Rectangle(2 * L["x_so"], zcol1 - zg)              # column
    ped = xz(prof, yp0, yp1)
    # column forward over the disc to form the sleeve's back wall, then the sleeve (A's layer) and its front wall
    zd = zg + p.disc_r + 0.6
    ped += box(-L["x_so"], L["x_so"], L["yA1"] + L["sl"], yp0 + 0.01, zd, zcol1)
    zs0 = zg + L["z_s0"]
    ped += box(-L["x_so"], L["x_so"], L["yA0"] - L["sl"] - p.sleeve_front, L["yA1"] + L["sl"] + 0.01, zs0, zcol1)
    ped -= box(-L["x_si"], L["x_si"], L["yA0"] - L["sl"], L["yA1"] + L["sl"], zs0 - 1, zcol1 + 1)
    y0w, f, xw = L["yA0"] - L["sl"], p.sleeve_front, L["x_si"]
    win = poly([(xw, y0w + 0.01), (xw - f, y0w - f), (xw - f, y0w - f - 1), (-(xw - f), y0w - f - 1), (-(xw - f), y0w - f), (-xw, y0w + 0.01)])
    ped -= Pos(0, 0, zs0 - 1) * extrude(win, zcol1 - zs0 + 2)
    # lead-in for the bumps at the sleeve bottom, and the three detent notches (45-deg flanks)
    sl = L["sl"]
    for s in (-1, 1):
        lead = Polygon((s * (L["x_si"] - 0.01), zs0 - 0.01), (s * (L["x_si"] + p.bump_h), zs0 - 0.01), (s * (L["x_si"] - 0.01), zs0 + p.bump_h + 0.2), align=None)
        ped -= xz(lead, L["yA0"] - sl, L["yA1"] + sl)
        apex = p.bump_h - sl + sl / cos(radians(45))
        for k in (-1, 0, 1):
            zc = zg + L["z_b"] + k * L["S"]
            notch = Polygon((s * (L["x_si"] - 0.01), zc - apex - 0.1), (s * (L["x_si"] + apex), zc - 0.1), (s * (L["x_si"] + apex), zc + 0.1),
                            (s * (L["x_si"] - 0.01), zc + apex + 0.1), align=None)
            ped -= xz(notch, L["yA0"] - sl, L["yA1"] + sl)
    # shaft bearing (vertical in print) with a +0.3 stepped relief at the plate
    rb = p.shaft_r + L["lo"]
    ped -= xz(Pos(0, zg) * Circle(rb), yp0 - 0.1, yp1 + 0.1)
    ped -= xz(Pos(0, zg) * Circle(rb + 0.3), yp1 - 0.6, yp1 + 0.1)
    # dovetail groove under the sill (through in Y)
    ped -= xz(poly(rail_ring(p, sl, ph).exterior.coords), yp0 - 0.1, yp1 - p.groove_back)   # blind at the back
    # latch: in-layer arm along X at the sill's foot, slit above, barb below its tip
    xr, xt = L["x_lr"], L["x_lt"]
    ped -= box(xr, xt + p.latch_slit, yp0 - 0.1, yp1 + 0.1, ph + p.latch_t, ph + p.latch_t + p.latch_slit)
    ped -= box(xt, xt + p.latch_slit, yp0 - 0.1, yp1 + 0.1, ph - 0.1, ph + p.latch_t + 0.01)
    ped = fillet_each(ped, 0.8, lambda q: q.edges().filter_by(Axis.Y).filter_by(
        lambda e: abs(e.center().X - xr) < 0.01 and abs(e.center().Z - (ph + p.latch_t + p.latch_slit)) < 0.01))
    # round the footprint's vertical corners (warping), except inside the latch
    zl = L["z_sill1"] + 0.1
    ped = fillet_each(ped, 1.5, lambda q: q.edges().filter_by(Axis.Y).filter_by(
        lambda e: e.length > 3.0 and max(v.Y for v in e.vertices()) > yp1 - 0.01
        and not (e.center().Z < zl and e.center().X > xr - 0.1)
        and not (abs(e.center().X) < p.rail_w / 2 + p.rail_h + 1.0 and e.center().Z < zl)
        and not (abs(e.center().Z - L["z_sill1"]) < 0.05 and abs(e.center().X) < p.sill_x - 1.0)), tries=40)
    ped = fillet_each(ped, 0.5, lambda q: q.edges().filter_by(Axis.Y).filter_by(
        lambda e: e.length > 3.0 and max(v.Y for v in e.vertices()) > yp1 - 0.01 and e.center().Z < zl
        and abs(e.center().X - xr) > 0.05 and abs(e.center().X) > p.rail_w / 2 + p.rail_h + 0.5
        and not (abs(e.center().Z - L["z_sill1"]) < 0.05 and abs(e.center().X) < p.sill_x - 1.0)), tries=40)
    hb = p.latch_barb
    barb = Polygon((yp0, ph + 0.01), (yp0 + hb + 0.2, ph - hb), (yp1, ph - hb), (yp1, ph + 0.01), align=None)
    ped += yz(barb, xt - p.barb_x0, xt - p.barb_x1)
    return ped


def make_crank(p, L):
    """Shaft frame: axis along Y through the origin, bed flat at z = -shaft_zf; arm along +X behind the pedestal."""
    r, zf = p.shaft_r, p.shaft_zf
    shaft = xz(tri_flat(r, zf), L["y_sh"], L["y_arm0"] + 0.5)
    th = p.tip_half
    tip = xz(Rectangle(2 * th, 2 * zf), L["y_tip"], L["y_sh"] + 0.5)
    rs = p.tine_slot / 2                                       # slit ends in a full radius (sharp roots ~3x strain)
    tt = th - rs                                               # tine thickness at the root; tapers to tine_taper x that at the tip
    wt = th - p.tine_taper * tt                                # slit half-width at the tip
    yr = L["y_tip"] + p.tine_l - rs
    tip -= Pos(0, 0, -zf - 0.5) * extrude(poly([(rs, yr), (-rs, yr), (-wt, L["y_tip"] - 0.1), (wt, L["y_tip"] - 0.1)]), 2 * zf + 1)
    tip -= Pos(0, L["y_tip"] + p.tine_l - rs, 0) * Cylinder(rs, 2 * zf + 1)
    for sx in (-1, 1):   # barbs: 45-deg lead-in toward the tip, flat catch face, 45-deg underside (prints lying)
        bx = Polygon((th - 0.01, L["y_tip"]), (th + p.barb, L["y_tip"] + p.barb), (th + p.barb, L["y_tip"] + p.barb_l),
                     (th - 0.01, L["y_tip"] + p.barb_l), align=None)
        barb = Pos(0, 0, -2.0) * extrude(bx, 3.5)
        barb &= xz(Polygon((th - 0.1, p.snap_z0), (th + p.barb + 0.1, p.snap_z0 + p.barb + 0.2), (th + p.barb + 0.1, p.snap_z1), (th - 0.1, p.snap_z1), align=None),   # underside > 2 mm off the bed
                   L["y_tip"] - 1, L["y_tip"] + p.barb_l + 1)
        tip += barb if sx > 0 else mirror(barb, about=Plane.YZ)
    shaft += tip
    hub_s = bar_sec(p.hub_r - 0.3, zf, p.hub_r, 0.8)
    knob_s = bar_sec(p.knob_r - 0.5, zf, p.knob_r, 1.8, p.crank_r, 0)
    hub = xz(hub_s, L["y_h0"], L["y_arm0"] + 0.5)
    R = p.crank_r
    arm = hub_s + knob_s
    arm += Polygon((0, -zf), (R, -zf), (R, p.arm_h - 0.4), (0, p.arm_h), align=None)
    arm = xz(arm, L["y_arm0"], L["y_arm1"])
    knob = xz(knob_s, L["y_arm1"] - 0.5, L["y_knob"])
    c = (shaft + hub + arm + knob).clean()
    sh = c.edges().filter_by(lambda e: abs(e.center().Y - L["y_h0"]) < 0.01 and e.center().Z > -zf + 0.3
                             and sqrt(e.center().X ** 2 + e.center().Z ** 2) < r + 0.3)
    c = fillet(c, 0.8, sh)
    c = fillet_each(c, 0.8, lambda q: q.edges().filter_by(Axis.Z).filter_by(
        lambda e: e.center().Z < 0.5 and e.length > 2 * zf - 0.1 and abs(e.center().Y - L["y_h0"]) > 0.1), tries=12)
    return c


# ---------------------------------------------------------------- motion
def _cache(p):
    cache = sys.__dict__.setdefault("_forge_rackframe_v3", {})
    key = hashlib.sha256(Path(__file__).read_bytes() + (HERE / "study_2d.py").read_bytes() + repr(sorted(
        (k, v) for k, v in vars(p).items() if k != "t_sel")).encode()).hexdigest()
    if key not in cache:
        cache.clear()
        L = layout(p)
        S = dict(base=make_base(p, L), pedestal=make_pedestal(p, L), frame=make_frame(p, L), cam=make_cam(p, L),
                 selector=make_selector(p, L), crank=make_crank(p, L))
        cache[key] = (L, S)
    return cache[key]


def pose(p, L):
    """(state, B's x, B/A dz, cam angle in deg about +Y) from t_sel. B's x is the 2D contact solve."""
    t = float(p.t_sel)
    S = L["S"]
    i = lambda th: min(int(round(th / 0.5)), len(L["up_x"]) - 1)
    ang = -(L["phi0"] + t)                       # CCW from the front = negative about +Y
    if t < 360:
        return "UP", float(L["up_x"][i(t)]), S, ang
    if t < 720:
        return "DOWN", float(L["dn_x"][i(t - 360)]), -S, ang
    return "NEUTRAL", float(L["dn_x"][-1]), 0.0, ang


def build(p) -> Design:
    L, S = _cache(p)
    zg = L["zg"]
    state, x, dz, a = pose(p, L)
    rot = ((0, 0, zg), (0, a, 0))
    parts = [
        Part("base", S["base"], color="#8A8F96", orient=(0, 0, 0), cosmetic=["-y", "+z"],
             notes="Plinth + two posts with open-top U bearings (left post on its curved arm) + dovetail rail + latch pocket."),
        Part("pedestal", S["pedestal"], color="#8A8F96", orient=(-90, 0, 0), cosmetic=["-y"],
             notes="Two uprights + bearing head + column + A's sleeve (3 detent notches) + sill with dovetail groove and latch. Printed on its back."),
        Part("frame", S["frame"], color="#8A8F96", placement=(x, 0, zg + dz), orient=(-90, 0, 0), cosmetic=["-y"],
             notes="Rack-frame B with its end rods, raised slotted bar, sawtooth racks, recessed web with B. Printed on its back."),
        Part("cam", S["cam"], color="#8A8F96", placement=rot, orient=(-90, 0, 0), cosmetic=["-y"],
             notes="D: 4-blade cam (study_2d.cam_shape) + disc, printed disc-down; blind keyed bore with snap grooves."),
        Part("selector", S["selector"], color="#8A8F96", placement=(0, 0, zg + dz), orient=(-90, 0, 0), cosmetic=["-y"],
             notes="A: rod + inverted-U fork + two pins; two in-layer detent flags; drag tongue. Printed on its back."),
        Part("crank", S["crank"], color="#8A8F96", placement=rot, orient=(0, 0, 0),
             notes="Shaft + split snap tip + hub + arm + knob behind the pedestal, printed lying on the shaft's flat."),
    ]
    zpin = zg + L["z_pin"]
    fits = [
        Fit("cam", "frame", "contact", retention="captured", drives=True,
            notes="Blade tips push the steep tooth faces (2D push-only solve; push_gap kept)."),
        Fit("cam", "crank", "snug", retention="snap", snap_case="shaft_snap",
            notes="Square split tip keys the cam; its barbs click into grooves in the blind bore."),
        Fit("cam", "pedestal", "loose", retention="captured", notes="Disc back face runs past the pedestal front."),
        Fit("crank", "pedestal", "loose", retention="captured", notes="Journal in the bearing; held between the crank hub and the snapped-on cam."),
        Fit("frame", "selector", "sliding", retention="captured", overlap_ok_mm3=1.5,
            region=Region((-40, -6, zpin - 6), (40, 0.5, zpin + 2.4)),
            notes="Pins in B's slot (0.2/side). A's drag nub presses B's bar 0.3 mm (intended overlap) so B doesn't drift."),
        Fit("frame", "base", "sliding", retention="captured",
            notes="Rods in the posts' U bearings (Y held, Z free by the stroke). B's Z is set by A's pins."),
        Fit("selector", "pedestal", "sliding", retention="snap", snap_case="detent",
            notes="A in its sleeve; two flags click into 3 notches (UP/NEUTRAL/DOWN). A's fork sits behind B's bar, so A can't leave forward."),
        Fit("pedestal", "base", "contact", retention="snap", snap_case="ped_latch",
            notes="Sill on the plinth, dovetail holds X and Z; the latch barb in the plinth pocket holds Y."),
    ]
    return Design(
        parts=parts, fits=fits, loads=loads(p, L),
        explode={"frame": (0, -40, 0), "selector": (0, -15, 30), "cam": (0, -25, 0), "crank": (0, 40, 0), "pedestal": (0, 30, 0)},
        motion=Motion("t_sel", 0, 1080, 15, min_travel_mm=12, exclude_travel=("cam", "crank", "selector")),
    )


def loads(p, L):
    R, zf = p.crank_r, p.shaft_zf
    jr = p.shaft_r + 0.5
    zg, ph = L["zg"], p.plinth_h
    # blade 0 tip (part frame, rest angle): study_2d puts blade k's tip at angle 90k + sweep from -Z
    rt = p.cam_r - p.blade_t / 2
    tx, tz = rt * sin(radians(p.blade_sweep)), -rt * cos(radians(p.blade_sweep))
    xb, xt = L["x_lr"], L["x_lt"]
    return [
        LoadCase("crank_push", part="crank",
                 fixed=Region((-jr, L["yp0"], -jr), (jr, L["yp1"], jr)),
                 load=Region((R - p.knob_r - 0.1, L["y_knob"] - p.knob_l / 2, -zf - 0.1), (R + p.knob_r + 0.1, L["y_knob"] + 0.1, p.knob_r + 0.1)),
                 force=(0, 0, -10), use="static", mesh_size=0.5,
                 refine=Region((-p.hub_r - 1, L["y_tip"] - 1, -p.knob_r - 1), (R + p.knob_r + 1, L["y_knob"] + 1, p.knob_r + 1)),
                 notes="10 N tangential push on the outer half of the knob; journal fixed (conservative)."),
        LoadCase("detent", part="selector",
                 fixed=Region((-L["fx"] - 0.1, L["yA0"] - 0.1, L["z_cr0"] - 0.1), (L["fx"] + 0.1, L["yA1"] + 0.1, L["z_cr0"] + 1.5)),
                 load=Region((L["x_fl1"] + p.bump_h - 0.08, L["yA0"] - 0.05, L["z_b"] - 0.15), (L["x_fl1"] + p.bump_h + 0.05, L["yA1"] + 0.05, L["z_b"] + 0.15)),
                 displacement=(-(p.bump_h - L["sl"]), 0, 0), nonlinear=True, use="repeated",
                 min_force_n=1.35, max_force_n=4.0, mesh_size=0.35,
                 refine=[Region((L["x_fl0"] - 1.5, L["yA0"] - 0.5, L["z_ct"] - 1.5), (L["x_fl1"] + p.bump_h + 0.5, L["yA1"] + 0.5, L["z_ftip"] + 0.5)),
                         Region((-p.pin_s / 2 - 2.5, L["yBf"], L["z_pin"] - 2.5), (-p.pin_s / 2 + 2.5, L["yA0"] + 0.5, L["z_pin"] + 2.5)),
                         Region((p.pin_s / 2 - 2.5, L["yBf"], L["z_pin"] - 2.5), (p.pin_s / 2 + 2.5, L["yA0"] + 0.5, L["z_pin"] + 2.5)),
                         Region((-p.pin_s / 2 + p.leg_w / 2 - 1.0, -p.drag_int - 0.2, L["z_cr0"] - 0.4 - p.drag_b - 1.0),
                                (-p.pin_s / 2 + p.leg_w / 2 + p.drag_l + 0.5, L["yA1"] + 0.2, L["z_cr0"] + 0.3))],
                 notes="One of two flags. Sleeve wall on the bump apex (a line along Y) while A moves between notches; crown fixed. "
                       "Displacement = engagement 1.0 mm. Feel limits are per flag: push = 2 flags x ~1.86 (45-deg flank, mu 0.3) x tip force, "
                       "so 1.35-4.0 N per flag = 5-15 N at the thumb."),
        LoadCase("shaft_snap", part="crank",
                 fixed=Region((-p.shaft_r - 0.5, L["y_sh"] - 0.5, -zf - 0.5), (p.shaft_r + 0.5, L["yp1"], p.shaft_r + 0.5)),
                 load=Region((p.tip_half + p.barb - 0.08, L["y_tip"] + p.barb + 0.1, p.snap_z0 + p.barb + 0.3), (p.tip_half + p.barb + 0.05, L["y_tip"] + p.barb_l - 0.1, p.snap_z1 - 0.1)),
                 displacement=(-(p.barb + 0.1), 0, 0), nonlinear=True, use="once", min_force_n=5, max_force_n=15, mesh_size=0.3,
                 refine=Region((-p.tip_half - p.barb - 0.5, L["y_tip"] - 0.5, -zf - 0.5), (p.tip_half + p.barb + 0.5, L["y_tip"] + p.tine_l + 1.5, zf + 0.5)),
                 notes="Cam bore wall on one barb's outer face (a line along Y) while the cam is pushed on; journal fixed. Assembled once."),
        LoadCase("ped_latch", part="pedestal",
                 fixed=Region((-p.sill_x - 0.1, L["yp0"] - 0.1, ph - 0.1), (-L["x_lr"], L["yp1"] + 0.1, L["z_sill1"] + 0.1)),
                 load=Region((xt - (p.barb_x0 + p.barb_x1) / 2 - 0.1, L["yp0"] + 2.0, ph - p.latch_barb - 0.05), (xt - (p.barb_x0 + p.barb_x1) / 2 + 0.1, L["yp1"] - 0.5, ph - p.latch_barb + 0.05)),
                 displacement=(0, 0, p.latch_barb + 0.1), nonlinear=True, use="once", min_force_n=5, max_force_n=15, mesh_size=0.3,
                 refine=[Region((xb - 1, L["yp0"] - 0.5, ph - p.latch_barb - 0.5), (xt + p.latch_slit + 0.5, L["yp1"] + 0.5, ph + p.latch_t + p.latch_slit + 1)),
                         Region((-p.shaft_r - 1.5, L["yp1"] - 1.5, zg - p.shaft_r - 1.5), (p.shaft_r + 1.5, L["yp1"] + 0.5, zg + p.shaft_r + 1.5))],
                 notes="Plinth top under the barb (a line along Y) while the pedestal slides on; sill's left half fixed. Assembled once."),
        LoadCase("blade_root", part="cam",
                 fixed=Region((-p.tip_half - 0.5, L["ycf"], -p.shaft_zf - 0.5), (p.tip_half + 0.5, L["yd1"], p.shaft_zf + 0.5)),
                 load=Region((tx - 0.7, L["ycf"] - 0.1, tz - 0.7), (tx + 0.7, L["yBb"], tz + 0.7)),
                 force=(-2.0, 0, 0), use="static", mesh_size=0.4,
                 refine=Region((-p.cam_hub_r - 0.5, L["ycf"] - 1, -p.cam_r - 0.5), (p.cam_r + 0.5, L["yd0"] + 0.5, 0.5)),
                 notes="2 N on one blade tip against the push (10x the < 0.5 N drive estimate, mechanism.md §3); bore walls fixed."),
        LoadCase("blade_stall", part="cam",
                 fixed=Region((-p.tip_half - 0.5, L["ycf"], -p.shaft_zf - 0.5), (p.tip_half + 0.5, L["yd1"], p.shaft_zf + 0.5)),
                 load=Region((tx - 0.7, L["ycf"] - 0.1, tz - 0.7), (tx + 0.7, L["yBb"], tz + 0.7)),
                 force=(2.0 * p.crank_r / p.cam_r * 5.0, 0, 0), use="static", mesh_size=0.4,
                 refine=Region((-p.cam_hub_r - 0.5, L["ycf"] - 1, -p.cam_r - 0.5), (p.cam_r + 0.5, L["yd0"] + 0.5, 0.5)),
                 notes="Reverse cranking stalls at the travel end (no run-off that way: the blade rides a back slope into the hand stop). "
                       "The full 10 N crank push then reaches one blade tip: 10 x crank_r / cam_r = 21.4 N, here on the tip's back face."),
    ]
