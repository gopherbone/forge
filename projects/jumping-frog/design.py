"""Jumping Frog: one extruded side-profile silhouette, printed lying on its side.

Part frame = USE frame: the frog stands on the table (z = 0), snout towards +X, the
silhouette is in the XZ plane and extruded symmetrically +-width/2 in Y.

Everything is one 2D profile extruded once, so every curve is a vertical wall in print and
all rounding is 2D vertex fillets (vertical edges in print). No 3D fillets or chamfers touch
either side face (user rule: walls meet the plate vertically).

Mechanism: the hind leg is a C-shaped strip (two bends joined by a straight back) that runs
from the rump down to a flat hind foot (the sole) on the table. Pressing the back closes the
C until the front leg's toe lands on the sole (hard stop). Slide the finger off and the C
snaps open: the body flicks up and pulls the foot off the table.
"""
from build123d import *

from forge.dsl import Design, LoadCase, Part, Region


def _near(face, pts, tol=0.25):
    """Vertices of a 2D face within tol of any of the given (x, y) points."""
    out = []
    for v in face.vertices():
        if any(abs(v.X - x) < tol and abs(v.Y - y) < tol for x, y in pts):
            out.append(v)
    return out


def frame(p) -> dict:
    """Key profile coordinates (2D x = world X, 2D y = world Z)."""
    t, r = p.spring_t, p.spring_r
    xc = r + t / 2                     # strip bends start here: the C's back is at x = 0
    zl = t / 2                         # lower strip centreline (strip bottom on the table)
    zu = zl + 2 * r + p.spring_h       # upper strip centreline
    zb = zu - t / 2                    # body underside, flush with the strip's inner face
    toe_z = p.sole_t + p.stop_gap
    x_toe0, x_toe1 = p.leg_x + p.leg_lean, p.leg_x + p.leg_lean + p.leg_w
    return dict(xc=xc, zl=zl, zu=zu, zb=zb, toe_z=toe_z, x_toe0=x_toe0, x_toe1=x_toe1,
                x_press=(x_toe0 + x_toe1) / 2, z_back=zb + p.back_h)


def profile(p) -> Face:
    f = frame(p)
    L, t, r = p.length, p.spring_t, p.spring_r
    xc, zl, zu, zb = f["xc"], f["zl"], f["zu"], f["zb"]
    cr = p.corner_r

    # body + head: flat back (finger land), head rising in front, vertical rump wall at the back
    xr = xc + 2 * p.root_r                     # rump starts a short straight forward of the upper bend
    zbel = zb - p.belly_drop                   # belly slopes down from the spring to the front leg
    head0 = L - p.head_len - p.eye_d - cr      # where the head rises from the back
    pts = [(xr, zb), (p.leg_x, zbel), (L - 2 * cr - p.chin_h, zbel), (L, zb + p.chin_h), (L, zb + p.snout_h),
           (L - p.head_len / 2, zb + p.head_h), (head0 + 2 * cr, zb + p.head_h),
           (head0, zb + p.back_h), (xr, zb + p.back_h)]
    body = make_face(Polyline(*pts, close=True))
    body = fillet(_near(body, pts[2:-1]), cr)   # not the leg junction or the rump corner (the knee covers it)

    # knee: a half-round ridge at the rear of the back, flush with the vertical rump wall.
    # A finger sliding backwards rides over it and drops off clear of the spring loop.
    knee_c = (xr + p.knee_r, zb + p.back_h)
    knee = Pos(*knee_c) * Circle(p.knee_r)

    # eye: a ring bump on the head with a through-hole
    eye_c = (L - p.head_len / 2 - p.eye_d / 2 - p.eye_wall, zb + p.head_h)
    ring = Pos(*eye_c) * Circle(p.eye_d / 2 + p.eye_wall)

    # front leg: rear edge raked forward out of the belly, front edge vertical; the flat toe is the stop
    toe_z = f["toe_z"]
    h_leg = zbel - toe_z
    x1 = f["x_toe1"]
    leg_pts = [(p.leg_x - p.leg_lean * cr / h_leg, zbel + cr), (x1, zbel + cr), (x1, toe_z), (f["x_toe0"], toe_z)]
    leg = make_face(Polyline(*leg_pts, close=True))
    leg = fillet(_near(leg, leg_pts[2:]), p.leg_w / 4)

    # hind foot: flat sole on the table, ramping into the strip at the back, webbed toes at the front
    w = p.toe_notch_w                          # notch width at the top
    r_tip = (p.toe_pitch - w) / 2 - 0.05       # toe-tip radius: rounds off the flat between notches
    notches = []
    for k in range(1, p.toe_notches + 1):
        xk = p.sole_end - k * p.toe_pitch
        notches += [(xk + w / 2, p.sole_t), (xk, p.sole_t - p.toe_notch_d), (xk - w / 2, p.sole_t)]
    sole_pts = [(xc, 0), (p.sole_end, 0), (p.sole_end, p.sole_t), *notches, (xc + p.sole_ramp, p.sole_t), (xc, t)]
    sole = make_face(Polyline(*sole_pts, close=True))
    sole = fillet(_near(sole, [(p.sole_end, 0)]), p.sole_t / 2 - 0.1)
    sole = fillet(_near(sole, [(p.sole_end, p.sole_t)]), p.toe_pitch - w / 2 - r_tip - 0.05)
    tips = [(x, y) for x, y in notches if y == p.sole_t]
    sole = fillet(_near(sole, tips, tol=0.05), r_tip)   # soften the toe tips (no sharp corners at the plate)

    # the spring: a C strip of thickness t, centreline radius r, straight back spring_h
    path = FilletPolyline((xc + 1, zl), (xc - r, zl), (xc - r, zu), (xr + 1, zu), radius=r)
    strip = trace(path, line_width=t)

    shape = body + knee + ring + leg + sole + strip
    face = shape.faces()[0] if len(shape.faces()) == 1 else shape.faces().sort_by(SortBy.AREA)[-1]

    # root fillets (concave): strip into rump and into foot; leg into belly
    face = fillet(_near(face, [(xr, zb + t), (xc, t)], tol=0.4), p.root_r)
    face = fillet(_near(face, [(p.leg_x, zbel), (x1, zbel)], tol=0.3), p.leg_w / 4)
    face = fillet(_near(face, [(xr + 2 * p.knee_r, zb + p.back_h)], tol=0.3), p.knee_r / 2)   # knee into the back

    # eye hole and the smile: a closed slit with round ends, stopping short of the snout tip
    face = face - Pos(*eye_c) * Circle(p.eye_d / 2)
    zm = zb + (p.chin_h + p.snout_h) / 2
    m0 = (L - p.mouth_inset, zm)
    m1 = (L - p.mouth_inset - p.mouth_len, zm + p.mouth_w * 1.5)
    smile = ThreePointArc(m0, (L - p.mouth_inset - p.mouth_len * 0.55, zm - p.mouth_w * 0.6), m1)
    face = face - (trace(smile, line_width=p.mouth_w) + Pos(*m0) * Circle(p.mouth_w / 2) + Pos(*m1) * Circle(p.mouth_w / 2))
    return face


def build(p) -> Design:
    f = frame(p)
    face = profile(p)
    frog = extrude(Plane.XZ * face, p.width / 2, both=True)

    W = p.width
    xp, zt = f["x_press"], f["z_back"]
    press = Region((xp - 0.4, -W, zt - 0.05), (xp + 0.4, W, zt + 0.05))        # fingertip: a line across the back
    foot = Region((f["xc"] + p.sole_ramp + 2, -W, -0.05), (p.sole_end - 2, W, 0.05))  # sole on the table
    spring_zone = Region((-0.5, -W, -0.5), (f["xc"] + p.sole_ramp + 1.5, W, f["zb"] + 4))
    loads = [
        LoadCase("spring", "frog", fixed=foot, load=press, displacement=(0, 0, -p.press_travel),
                 nonlinear=True, use="repeated", steps=10, min_force_n=2, max_force_n=15,
                 mesh_size=round(p.spring_t / 3, 3), refine=spring_zone,
                 notes=f"Fingertip line across the back above the front toe, pushed down {p.press_travel} mm "
                       f"(travel to the hard stop: toe {p.stop_gap} mm above the sole). Sole underside fixed "
                       "(the table; ignores the foot sliding). No contact modelled."),
    ]
    return Design(
        parts=[Part("frog", frog, color="#5cb85c", orient=(90, 0, 0), cosmetic=["+y", "-y"],
                    notes="Printed on its side: the silhouette is the show face (one on the textured plate, "
                          "one up). The C spring bends in the print plane, along the layers.")],
        loads=loads,
    )
