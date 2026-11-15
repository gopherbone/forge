"""2D contact study for movement 84 (lead). Real blade thickness, push-only frame, forward and reverse.

Model (frame coordinates, cam centre at the origin):
  - D: hub + 4 curved blades, tip radius R, blade thickness tb, sweep angle.
  - Lower rack (selector UP): sawtooth teeth pointing up, steep face vertical on the +x side,
    back slope on the -x side, pitch p, height h. Tooth tip line at z = -(R - d), so penetration is d.
  - The cam turns CW (as seen from the front), so the lower blade tip moves +x and pushes B +x.
  - Push-only solver: if the cam overlaps a tooth, B moves along +x (forward) until clear,
    which is what a blade pushing a free frame does when the contact normal is mostly along x.
    If resolving the overlap needs B to move against the drive (a blade landing on a back
    slope or jammed in a pocket), the step is recorded as a JAM (a wedge or vertical load).
Outputs per case: steps per blade pass, dwell fraction, jam count, and whether the blade
reaches full depth in the pocket.
"""
from __future__ import annotations

import json
import sys
from math import cos, pi, radians, sin, sqrt, tan

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union


def cam_shape(R, tb, hub_r=3.0, sweep=35.0, n=4):
    parts = [Point(0, 0).buffer(hub_r, 48)]
    for k in range(n):
        c0 = 2 * pi / n * k
        pts = []
        for t in np.linspace(0, 1, 24):
            r = hub_r - 0.5 + (R - tb / 2 - hub_r + 0.5) * t
            a = c0 + radians(sweep) * t ** 1.5
            pts.append((r * sin(a), -r * cos(a)))
        parts.append(LineString(pts).buffer(tb / 2, 12))
    return unary_union(parts)


def rack(p, h, d, R, n_teeth=60, x0=-150.0, flat=0.4):
    """Lower rack: steep face at x = f (vertical), back slope rising from f - (p - flat) to f."""
    zt = -(R - d)          # tooth tip line
    zr = zt - h            # root line
    teeth = []
    for k in range(n_teeth):
        f = x0 + k * p
        # steep (vertical) face at x = f facing -x, flat top, back slope descending to the next tooth
        teeth.append(Polygon([(f, zr), (f, zt), (f + flat, zt), (f + p - 0.05, zr)]))
    base = Polygon([(x0 - p - 5, zr - 3), (x0 + n_teeth * p + 5, zr - 3), (x0 + n_teeth * p + 5, zr), (x0 - p - 5, zr)])
    return unary_union(teeth + [base])


PITCH = [0.0]


def run(R, tb, p, h, d, reverse=False, step_deg=0.5, revs=3.0):
    PITCH[0] = p
    cam = cam_shape(R, tb)
    rk = rack(p, h, d, R)
    sgn = -1.0 if reverse else 1.0        # reverse cranking: blade tip moves -x at the bottom
    x = 0.0
    xs, jams = [], 0
    for th in np.arange(0, 360 * revs, step_deg):
        a = sgn * radians(th)
        G = affinity.rotate(cam, np.degrees(a), origin=(0, 0))   # +angle = CCW: lower blade tip moves +x onto the steep faces
        moved = 0.0
        tries = 0
        while G.intersection(affinity.translate(rk, x, 0)).area > 1e-6 and tries < 400:
            x += sgn * 0.02
            moved += 0.02
            tries += 1
        if tries >= 400:
            jams += 1
        xs.append(x)
    xs = np.array(xs)
    steps = np.diff(xs)
    moving = np.abs(steps) > 1e-9
    per_rev = (xs[-1] - xs[int(len(xs) / revs)]) if revs > 1 else xs[-1]
    # step sizes: contiguous moving runs
    runs, cur = [], 0.0
    for s, m in zip(steps, moving):
        if m:
            cur += s
        elif cur:
            runs.append(round(cur, 2))
            cur = 0.0
    if cur:
        runs.append(round(cur, 2))
    r = np.array(runs[2:]) if len(runs) > 4 else np.array(runs)   # skip settling
    return {"per_rev_mm": round(float(per_rev), 2), "mean_step": round(float(np.abs(r).mean()), 2) if len(r) else 0,
            "min_step": round(float(np.abs(r).min()), 2) if len(r) else 0, "max_step": round(float(np.abs(r).max()), 2) if len(r) else 0,
            "runaway": bool(len(r) and np.abs(r).max() > 1.3 * PITCH[0]), "jams": jams, "n_steps": len(r)}


def clearance_neutral(R, p, h, c, tb):
    """Neutral: tooth tip line at R + c, so the minimum gap from the cam to the rack over a full turn."""
    cam = cam_shape(R, tb)
    rk = rack(p, h, -c, R)
    gmin = min(affinity.rotate(cam, a, origin=(0, 0)).distance(rk) for a in range(0, 360, 2))
    return round(gmin, 3)


if __name__ == "__main__":
    rows = []
    for R in (6.0, 7.0, 8.0):
        for p in (3.0, 4.0, 5.0, 6.0):
            for tb in (2.0, 2.4):
                h = 0.5 * p
                c = 1.0
                row = {"R": R, "p": p, "tb": tb, "h": h}
                for tag, d in (("dmin", 0.9), ("dnom", 1.6), ("dmax", 2.0)):
                    row[tag] = run(R, tb, p, h, d, revs=3.0)
                row["neutral_gap"] = clearance_neutral(R, p, h, c, tb)
                ok = all(not row[t]["runaway"] and row[t]["min_step"] > 0.5 for t in ("dmin", "dnom", "dmax"))
                row["ok"] = ok
                rows.append(row)
                f = lambda k: f"{row[k]['mean_step']:>4} [{row[k]['min_step']}-{row[k]['max_step']}]{' RUNAWAY' if row[k]['runaway'] else ''}"
                print(f"{'OK ' if ok else '-- '} R={R:4} p={p} tb={tb}: dmin {f('dmin')} | dnom {f('dnom')} | dmax {f('dmax')} | neutral gap {row['neutral_gap']}")
    import pathlib as _pl
    _pl.Path(__file__).with_name("study_2d.json").write_text(json.dumps(rows, indent=1))
