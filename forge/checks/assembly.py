"""Assembly checks on exact B-rep geometry (OpenCascade), not meshes.

- Undeclared pairs must not overlap (touching is fine).
- Declared fits must have the clearance their kind calls for, measured as the
  minimum surface-to-surface distance inside the fit's region."""
from __future__ import annotations

from itertools import combinations

from .. import config
from . import check


def _bbox_overlap(a, b, pad=0.5):
    A, B = a.bounding_box(), b.bounding_box()
    amin, amax, bmin, bmax = (tuple(v) for v in (A.min, A.max, B.min, B.max))
    return all(amin[i] - pad <= bmax[i] and bmin[i] - pad <= amax[i] for i in range(3))


def _clip(shape, region):
    from build123d import Box, Location
    lo, hi = region.min, region.max
    size = [hi[i] - lo[i] for i in range(3)]
    ctr = [(hi[i] + lo[i]) / 2 for i in range(3)]
    return shape & Box(*size).moved(Location(ctr))


def run(shapes: dict, fits: list) -> list[dict]:
    table = config.fits_table()
    declared = {frozenset((f.a, f.b)): f for f in fits}
    for f in fits:
        for n in (f.a, f.b):
            if n not in shapes:
                raise config.ForgeError(f"Fit {f.a}/{f.b} names unknown part {n!r}")
        if f.kind not in table:
            raise config.ForgeError(f"Fit kind {f.kind!r} unknown; use one of {list(table)}")
    out = []
    for a, b in combinations(shapes, 2):
        A, B = shapes[a], shapes[b]
        f = declared.get(frozenset((a, b)))
        near = _bbox_overlap(A, B)
        ov = 0.0
        if near:
            inter = A & B
            ov = float(inter.volume) if inter is not None else 0.0
        if f is None:
            if not near:
                continue
            gap = A.distance_to(B)
            if ov > 1e-3:
                st, det = "fail", "Parts with no declared fit must not overlap."
            elif gap < 0.15:
                st, det = "warn", (f"Touching or nearly touching ({gap:.3f} mm) with no declared fit. Coplanar faces rub, bind or "
                                   "fuse when printed together. Leave a real gap, or declare a `contact`/`sliding` Fit if intended.")
            else:
                st, det = "pass", "Clear."
            out.append(check(f"interf:{a}|{b}", f"{a} ↔ {b}: no collision", st, "verified",
                             value={"overlap_mm3": round(ov, 4), "min_gap_mm": round(gap, 3)}, detail=det))
            continue
        want = table[f.kind]["gap"]
        try:
            AA, BB = (_clip(A, f.region), _clip(B, f.region)) if f.region else (A, B)
            gap = AA.distance_to(BB)
        except Exception as e:
            out.append(check(f"fit:{a}|{b}", f"{a} ↔ {b}: {f.kind} fit", "fail", "verified",
                             detail=f"Could not measure (region empty?): {e}"))
            continue
        if f.kind == "press":
            st = "pass" if ov > 0 else "warn"
            det = "Press fit: some overlap expected."
        elif ov > f.overlap_ok_mm3 + 1e-3:
            st, det = "fail", f"Overlap {ov:.3f} mm³ where a {f.kind} fit needs a {want} mm gap."
        elif f.kind == "contact":
            st, det = "pass", "Faces touch without overlapping."
        elif gap < want - 0.02:
            st, det = "fail", f"Too tight: {gap:.3f} mm at the tightest point, {f.kind} wants ≥ {want} mm per side."
        elif gap > want + 0.3:
            st, det = "warn", f"Looser than intended: {gap:.3f} mm vs {want} mm. Wobbly?"
        else:
            st, det = "pass", f"{gap:.3f} mm per side at the tightest point (target {want} mm)."
        cal = "" if config.fits_calibrated() else " Clearances are uncalibrated defaults (run `forge coupon`)."
        out.append(check(f"fit:{a}|{b}", f"{a} ↔ {b}: {f.kind} fit", st, "verified",
                         value={"min_gap_mm": round(gap, 3), "target_mm": want, "overlap_mm3": round(ov, 4)},
                         detail=det + cal + (f" {f.notes}" if f.notes else "")))
    return out
