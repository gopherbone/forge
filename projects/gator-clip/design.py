"""Gator Clip: one extruded side-profile silhouette, printed lying on its side.

Part frame = USE frame: the gator stands on its feet (z = 0 is the table), snout towards +X,
the silhouette is in the XZ plane and extruded symmetrically +-width/2 in Y.

All rounding is 2D vertex fillets (vertical edges in print); no 3D fillets or chamfers touch
either side face (user rule: walls meet the plate vertically).

Mechanism (clothespin topology, planar, nothing crosses):
- upper lever = upper jaw + forehead bridge + a short squeeze tab behind the head (thumb ridge)
- frame       = lower jaw + throat bridge + belly, legs and tail (the handle you hold)
They meet ONLY through a 3-leg vertical meander in a window behind the mouth corner: it is the
pivot and the spring. Its legs run parallel to the squeeze force, so the bending moment along
each leg is near-uniform. The mouth rests closed (0.6 mm gap); pressing the thumb ridge towards
the front legs rotates the upper jaw open until the tab's rear corner lands on the belly (the
hard stop at the end of the wedge slot under the tab).
"""
import math

from build123d import *

from forge.dsl import Design, LoadCase, Part, Region


def _near(face, pts, tol=0.25):
    """Vertices of a 2D face within tol of any of the given (x, y) points."""
    return [v for v in face.vertices() if any(abs(v.X - x) < tol and abs(v.Y - y) < tol for x, y in pts)]


def _main(shape):
    return shape.faces()[0] if len(shape.faces()) == 1 else shape.faces().sort_by(SortBy.AREA)[-1]


def frame(p) -> dict:
    """Key profile coordinates (2D x = world X, 2D y = world Z)."""
    t, g, c = p.hinge_t, p.hinge_gap, p.hinge_clear
    xc = p.length - p.jaw_len                       # pivot: hinge window centre
    ww = 3 * t + 2 * g + 2 * c
    zwb = p.leg_h + p.bridge_t
    zwt = zwb + p.window_h
    zm = (zwb + zwt) / 2                            # mouth line
    ztop = zwt + p.bridge_t                         # head / back top line
    legs = [xc - ww / 2 + c + t / 2 + i * (t + g) for i in range(3)]
    ru = (t + g) / 2
    # teeth: zigzag on the mouth line; '+' points are lower-tooth tips, '-' points upper-tooth tips
    x0 = xc + p.teeth_start
    zz = [(x0 + p.tooth_pitch / 4 + k * p.tooth_pitch / 2, zm + (p.tooth_h / 2 if k % 2 == 0 else -p.tooth_h / 2))
          for k in range(2 * p.teeth_n)]
    phi = math.atan2(p.tooth_h, p.tooth_pitch / 2)
    v = p.mouth_gap / (2 * math.cos(phi))           # vertical half-gap on the flanks
    interlock = p.tooth_h - 2 * v                   # upper tips sit this far below lower tips at rest
    xF = xc - p.thumb_b
    zF = ztop + p.ridge_r                           # top of the thumb ridge
    zsu = zm + p.mouth_gap / 2                      # tab underside
    return dict(xc=xc, ww=ww, xw0=xc - ww / 2, xw1=xc + ww / 2, zwb=zwb, zwt=zwt, zm=zm, ztop=ztop,
                legs=legs, ru=ru, zz=zz, v=v, interlock=interlock, x_teeth_end=x0 + p.teeth_n * p.tooth_pitch,
                xF=xF, zF=zF, zsu=zsu)


def eye_centres(p):
    f = frame(p)
    return [(f["xc"] + p.eye1_dx, f["ztop"] + p.eye1_dz), (f["xc"] + p.eye2_dx, f["ztop"] + p.eye2_dz)]


def profile(p) -> Face:
    f = frame(p)
    L, xc, zm, ztop = p.length, f["xc"], f["zm"], f["ztop"]
    hs = p.snout_h / 2

    # --- outer silhouette: wedge snout, flat head/back, tapering pointed tail, flat belly ---
    tail_top = (p.tail_x, ztop)
    pts = [(L, zm - hs), (L, zm + hs), (xc + p.forehead_x, ztop), tail_top, (0, p.tail_tip_z),
           (p.belly_x, p.leg_h), (xc + p.chin_x, p.leg_h)]
    body = make_face(Polyline(*pts, close=True))
    body = fillet(_near(body, pts[:2]), p.snout_r)
    body = fillet(_near(body, [pts[4]]), p.tail_r)
    body = fillet(_near(body, [pts[2], pts[3], pts[5], pts[6]]), p.body_r)

    # --- eye bumps: two round bumps standing up on the head, each with a dot pupil ---
    eyes = eye_centres(p)
    for e in eyes:
        body = body + Pos(*e) * Circle(p.eye_r)

    # --- scalloped back ridges, shrinking towards the tail; the first is the thumb pad on the tab ---
    def top_z(x):   # back line height at x (flat to tail_x, then straight down to the tail point)
        if x >= p.tail_x:
            return ztop
        return p.tail_tip_z + (ztop - p.tail_tip_z) * x / p.tail_x
    # ridges shrink evenly from the thumb ridge (on the tab) to the tail: the arc slot sits in the
    # valley between the first two, the rest are evenly spaced down the back to ridge_tail_x
    x_arc_out = xc - math.sqrt((p.tab_r + p.arc_gap) ** 2 - (ztop - zm) ** 2)   # arc slot's rear edge at the top line
    radii = [p.ridge_r * p.ridge_shrink ** k for k in range(p.ridges)]
    x2 = x_arc_out - p.ridge_gap - radii[1]
    pitch = (x2 - p.ridge_tail_x) / (p.ridges - 2)
    for k, r in enumerate(radii):
        x = f["xF"] if k == 0 else x2 - (k - 1) * pitch
        body = body + Pos(x, top_z(x)) * Circle(r)

    # --- legs: two front, two hind, short and straight; toe notches on the hind feet ---
    # each pair is one block with a round-topped slot between the two legs (no tiny flats to mesh)
    g = p.leg_pair_gap
    for xm in (p.front_leg_x, p.hind_leg_x):
        x0, x1 = xm - g / 2 - p.leg_w, xm + g / 2 + p.leg_w
        lp = [(x0, p.leg_h + 1), (x0, 0), (x1, 0), (x1, p.leg_h + 1)]
        pair = make_face(Polyline(*lp, close=True))
        pair = pair - (Pos(xm, (p.leg_h - g / 2) / 2 - 0.5) * Rectangle(g, p.leg_h - g / 2 + 1)
                       + Pos(xm, p.leg_h - g / 2) * Circle(g / 2))
        feet = [(x0, 0), (xm - g / 2, 0), (xm + g / 2, 0), (x1, 0)]
        pair = fillet(_near(pair, feet, tol=0.05), p.foot_r)
        for xl in (x0, xm + g / 2) if xm != p.front_leg_x else ():   # front feet stay flat: the finger pad
            for k in (1, 2):   # two V notches into the front of each sole: three little toes
                xn = xl + p.leg_w - k * p.leg_w / 3
                pair = pair - make_face(Polyline((xn - p.toe_w / 2, -0.01), (xn, p.toe_w), (xn + p.toe_w / 2, -0.01), close=True))
            toes = [(xl + p.leg_w - k * p.leg_w / 3 + s * p.toe_w / 2, 0) for k in (1, 2) for s in (1, -1)]
            pair = fillet(_near(pair, toes, tol=0.05), p.toe_r)    # round the toe tips (no sharp corners)
        body = body + pair
    face = _main(body)
    # concave fillets: outer leg edges into the belly
    junction = [(xm + s * (g / 2 + p.leg_w), p.leg_h) for xm in (p.front_leg_x, p.hind_leg_x) for s in (1, -1)]
    face = fillet(_near(face, junction, tol=0.3), p.inner_r)

    # --- hinge window + meander spring ---
    window = Pos(xc, (f["zwb"] + f["zwt"]) / 2) * Rectangle(f["ww"], p.window_h)
    window = fillet(window.vertices(), p.inner_r)
    t, ru = p.hinge_t, f["ru"]
    x_a, x_b, x_c = f["legs"]
    # U-turns shifted up by u_shift: the thumb load drags the meander down ~0.8 mm at the stop
    zu1 = f["zwb"] + p.hinge_clear + t / 2 + ru + p.u_shift     # lower U-turn centre
    zu2 = f["zwt"] - p.hinge_clear - t / 2 - ru + p.u_shift     # upper U-turn centre
    path = [Line((x_a, f["zwt"] + 0.6), (x_a, zu1)),
            CenterArc((x_a + ru, zu1), ru, 180, 180),
            Line((x_b, zu1), (x_b, zu2)),
            CenterArc((x_b + ru, zu2), ru, 180, -180),
            Line((x_c, zu2), (x_c, f["zwb"] - 0.6))]
    strip = trace(path, line_width=t)

    # --- mouth: zigzag slot from the window to the snout tip ---
    zz = f["zz"]
    mpts = [(f["xw1"] - 0.5, zm), (xc + p.teeth_start, zm), *zz, (f["x_teeth_end"], zm), (L + 1, zm)]
    mouth = trace(Polyline(*mpts), line_width=p.mouth_gap)

    # --- stop slot (wedge under the tab) + arc slot behind the tab ---
    zsu = f["zsu"]
    xr = xc - p.tab_r                                # tab rear corner (at the underside)
    xw0 = f["xw0"]

    def floor(x):   # stop-slot floor (belly top): stop_near deep at the window, stop_gap under the tab corner
        return zsu - p.stop_near + (p.stop_near - p.stop_gap) * (xw0 - x) / (xw0 - xr)
    ro = p.tab_r + p.arc_gap
    x_fl = xr
    for _ in range(30):   # where the floor meets the arc slot's rear face
        x_fl = xc - math.sqrt(ro ** 2 - (zm - floor(x_fl)) ** 2)
    x_far = xc - ro - 1.0
    slot = make_face(Polyline((xw0 + 0.5, zsu), (xw0 + 0.5, floor(xw0 + 0.5)), (x_fl, floor(x_fl)),
                              (xc - math.sqrt(ro ** 2 - (zsu - zm) ** 2), zsu), close=True))
    # arc slot: an annulus about the pivot, from the stop floor up and out through the back
    ring = Pos(xc, zm) * Circle(p.tab_r + p.arc_gap) - Pos(xc, zm) * Circle(p.tab_r)
    clip = make_face(Polyline((x_far, floor(x_far)), (xw0, floor(xw0)), (xw0, ztop + 1), (x_far, ztop + 1), close=True))
    arc = ring & clip

    face = _main(face - window + strip - mouth - slot - arc)

    # concave root fillets where the meander meets the bridges
    face = fillet(_near(face, [(x_a - t / 2, f["zwt"]), (x_a + t / 2, f["zwt"]),
                               (x_c - t / 2, f["zwb"]), (x_c + t / 2, f["zwb"])], tol=0.05), p.root_r)
    # blunt teeth: round every zigzag vertex on both jaws
    v = f["v"]
    tooth_v = [(x, z + s * v) for x, z in zz for s in (1, -1)]
    tooth_v += [(xc + p.teeth_start, zm + s * p.mouth_gap / 2) for s in (1, -1)]
    tooth_v += [(f["x_teeth_end"], zm + s * p.mouth_gap / 2) for s in (1, -1)]
    face = fillet(_near(face, tooth_v, tol=0.15), p.tooth_r)
    # snout tip mouth corners, slot corners (stop corner, tab corners)
    soft = [(L, zm + p.mouth_gap / 2), (L, zm - p.mouth_gap / 2)]
    face = fillet(_near(face, soft, tol=0.05), p.edge_r)
    # stop: round the tab's rear underside corner (the contact) and the wedge's rear floor corner
    face = fillet(_near(face, [(xr, zsu)], tol=0.3), p.stop_r)
    face = fillet(_near(face, [(x_fl, floor(x_fl))], tol=0.1), p.stop_r)
    # break the remaining convex corners: jaw roots and stop slot at the window, arc-slot exits at the back
    dz = ztop - zm
    x_in = xc - math.sqrt(p.tab_r ** 2 - dz ** 2)
    x_out = xc - math.sqrt((p.tab_r + p.arc_gap) ** 2 - dz ** 2)
    face = fillet(_near(face, [(f["xw1"], zm + p.mouth_gap / 2), (f["xw1"], zm - p.mouth_gap / 2),
                               (xw0, zsu), (xw0, floor(xw0))], tol=0.1), p.edge_r)
    face = fillet(_near(face, [(x_in, ztop)], tol=0.2), p.inner_r)
    face = fillet(_near(face, [(x_out, ztop)], tol=0.2), p.ridge_gap / 2.4)   # 125 deg corner: must fit the short flat (ridge_gap) to the next ridge

    # pupils
    for e in eyes:
        face = face - Pos(e[0] + p.pupil_dx, e[1] + p.pupil_dz) * Circle(p.eye_d / 2)
    return face


def build(p) -> Design:
    f = frame(p)
    face = profile(p)
    gator = extrude(Plane.XZ * face, p.width / 2, both=True)

    W = p.width
    xc, zm = f["xc"], f["zm"]
    # thumb: a line across the top of the first back ridge (on the tab)
    thumb = Region((f["xF"] - 0.4, -W, f["zF"] - 0.06), (f["xF"] + 0.4, W, f["zF"] + 0.06))
    # finger: under the two front feet
    x0 = p.front_leg_x - p.leg_pair_gap / 2 - p.leg_w
    feet = Region((x0 + 0.5, -W, -0.05), (x0 + 2 * p.leg_w + p.leg_pair_gap - 0.5, W, 0.05))
    hinge_zone = Region((f["xw0"] - 1.0, -W, f["zwb"] - 1.5), (f["xw1"] + 1.0, W, f["zwt"] + 1.5))
    # thumb ridge + the ridge behind the arc slot: small curved features where a coarse tet inverted (clamp v2)
    # the round-topped slots between each leg pair (small radius in coarse tets inverted twice)
    legs_zone = [Region((xm - 1.6, -W, 1.0), (xm + 1.6, W, p.leg_h + 0.6)) for xm in (p.front_leg_x, p.hind_leg_x)]
    pupils = [Region((ex + p.pupil_dx - 2.2, -W, ez + p.pupil_dz - 2.2), (ex + p.pupil_dx + 2.2, W, ez + p.pupil_dz + 2.2)) for ex, ez in eye_centres(p)]
    back_zone = Region((f["xF"] - 11, -W, f["ztop"] - 0.5), (f["xF"] + p.ridge_r + 0.3, W, f["ztop"] + p.ridge_r + 0.5))

    # clamp case: the roll between the frontmost upper tooth tip and the lower tooth behind it
    zz = f["zz"]
    up = min((q for q in zz if q[1] < zm), key=lambda q: abs(q[0] - (xc + p.seat_a)))
    lo = max((q for q in zz if q[1] > zm and q[0] < up[0]), key=lambda q: q[0])
    tip_up = up[1] + f["v"]           # upper tooth tip (before the tip radius)
    roll_up = Region((up[0] - 0.4, -W, tip_up - 0.05), (up[0] + 0.4, W, tip_up + 0.4))
    d8 = round(8 + f["interlock"], 2)   # Ø8 roll: tooth tips go from -interlock to +8 apart

    loads = [
        LoadCase("open", "gator", fixed=feet, load=thumb, displacement=(0, 0, -p.press_travel),
                 nonlinear=True, use="repeated", steps=5, min_force_n=5, max_force_n=15,
                 mesh_size=round(p.hinge_t / 2.7, 3), refine=[hinge_zone, back_zone, *legs_zone, *pupils],
                 notes=f"Thumb line across the top of the first back ridge ({p.thumb_b} mm behind the pivot), "
                       f"pushed down {p.press_travel} mm against the two front feet (the finger, fixed). "
                       "Travel set so the tab's rear corner just lands on the stop. No contact modelled."),
        LoadCase("clamp", "gator", fixed=feet, load=roll_up, displacement=(0, 0, d8),
                 nonlinear=True, use="repeated", steps=6, min_force_n=1, max_force_n=4,
                 mesh_size=round(p.hinge_t / 2.7, 3), refine=[hinge_zone, back_zone, *legs_zone, *pupils],
                 notes=f"Roll seat {p.seat_a} mm ahead of the pivot: the upper tooth tip at x={up[0]:.1f} is pushed up "
                       f"{d8} mm (Ø8 + {f['interlock']:.2f} mm tooth interlock) against the front feet (fixed; the lower jaw is rigid and unloaded). "
                       f"The curve gives clamp force vs roll size: Ø4 at {4 + f['interlock']:.2f} mm, Ø6 at "
                       f"{6 + f['interlock']:.2f} mm, Ø8 at the end."),
    ]
    return Design(
        parts=[Part("gator", gator, color="#7bc96f", orient=(90, 0, 0), cosmetic=["+y", "-y"],
                    notes="Printed on its side: the silhouette is the show face (one on the textured plate, one up). "
                          "The meander spring bends in the print plane, along the layers.")],
        loads=loads,
    )
