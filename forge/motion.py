"""Motion sweep for mechanisms (automata, linkages, gearboxes).

A design declares `Design(motion=Motion("crank_deg", 0, 360, 15))`. design.py must place
its moving parts from that param. The sweep rebuilds the design at every pose and, on
exact B-rep geometry:
  - checks every pair of parts for overlap (declared fits may allow a small amount),
  - records the tightest gap per pair across the cycle,
  - measures how far each part travels (centroid translation, rotation),
  - exports per-pose STLs so the renderer can animate the cycle."""
from __future__ import annotations

import json
from itertools import combinations

import numpy as np

from . import config
from .checks import check
from .geometry import occ_transform, placement_matrix


def _rotation_angle(M0, M1) -> float:
    R = M1[:3, :3] @ M0[:3, :3].T
    c = np.clip((np.trace(R) - 1) / 2, -1, 1)
    return float(np.degrees(np.arccos(c)))


def sweep(proj, export_every: int = 2) -> tuple[list[dict], dict]:
    from build123d import export_stl

    design0 = proj.load_design()
    mot = design0.motion
    if mot is None:
        return [], {}
    values = list(np.arange(mot.start, mot.stop, mot.step))
    declared = {frozenset((f.a, f.b)): f for f in design0.fits}
    names = [p.name for p in design0.parts]
    worst = {frozenset(pr): {"min_gap": float("inf"), "max_overlap": 0.0, "at": None} for pr in combinations(names, 2)}
    track = {n: [] for n in names}
    outdir = proj.build_dir / "motion"
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("*.stl"):
        old.unlink()
    frames = []
    poses = []
    vol0: dict[str, float] = {}
    deforming: set[str] = set()
    for i, v in enumerate(values):
        d = proj.load_design({mot.param: float(v)})
        shapes = {}
        for p in d.parts:
            s = p.shape.part if hasattr(p.shape, "part") else p.shape
            M = placement_matrix(p.placement)
            shapes[p.name] = occ_transform(s, M)
            vol = s.volume
            if p.name not in vol0:
                vol0[p.name] = vol
            elif abs(vol - vol0[p.name]) > 1e-3 * max(vol0[p.name], 1e-9):
                deforming.add(p.name)  # shape itself changes with the motion param: transform playback won't do
            c = shapes[p.name].center()
            track[p.name].append((np.array([c.X, c.Y, c.Z]), M))
        poses.append({"t": float(v), "M": {n: [round(x, 6) for x in track[n][-1][1].ravel()] for n in names}})
        for a, b in combinations(names, 2):
            A, B = shapes[a], shapes[b]
            bb_a, bb_b = A.bounding_box(), B.bounding_box()
            if any(tuple(bb_a.min)[k] - 1 > tuple(bb_b.max)[k] or tuple(bb_b.min)[k] - 1 > tuple(bb_a.max)[k] for k in range(3)):
                continue
            inter = A & B
            ov = float(inter.volume) if inter is not None else 0.0
            gap = 0.0 if ov > 1e-6 else A.distance_to(B)
            w = worst[frozenset((a, b))]
            if gap < w["min_gap"]:
                w["min_gap"], w["gap_at"] = gap, float(v)
            if ov > w["max_overlap"]:
                w["max_overlap"], w["at"] = ov, float(v)
        if i % export_every == 0:
            tag = f"{int(round(v)):03d}"
            for n, s in shapes.items():
                export_stl(s, outdir / f"{tag}_{n}.stl", tolerance=0.02, angular_tolerance=0.15)
            frames.append(tag)
    checks = []
    table = config.fits_table()
    for f in design0.fits:  # driving pairs must actually reach each other somewhere in the cycle
        if not getattr(f, "drives", False):
            continue
        w = worst.get(frozenset((f.a, f.b)))
        allow = table.get(f.kind, {}).get("gap", 0.0) + 0.25
        g = w["min_gap"] if w else float("inf")
        st = "pass" if g <= allow else "fail"
        checks.append(check(f"engage:{f.a}|{f.b}", f"{f.a} drives {f.b}: engagement", st, "verified",
                            value={"closest_mm": round(min(g, 99), 3)}, limit={"max_gap_mm": round(allow, 3)},
                            detail=("They come within driving distance during the cycle." if st == "pass" else
                                    f"The driver never gets closer than {g:.2f} mm, so it can't drive anything. Enlarge the "
                                    "driver, move the parts closer, or check the selector stroke.")))
    for pair, w in worst.items():
        a, b = sorted(pair)
        f = declared.get(pair)
        allow = f.overlap_ok_mm3 if f else 0.0
        if w["max_overlap"] > allow + 1e-3:
            st, det = "fail", f"Collide at {mot.param}={w['at']:g}: {w['max_overlap']:.3f} mm³ overlap."
        elif w["min_gap"] == float("inf"):
            continue
        elif f is None and w["min_gap"] < 0.15:
            st, det = "warn", (f"Undeclared pair gets within {w['min_gap']:.3f} mm (at {mot.param}={w.get('gap_at', 0):g}): "
                               "touching moving parts rub or bind. Add clearance or declare the fit.")
        else:
            st, det = "pass", f"Tightest gap over the cycle {w['min_gap']:.3f} mm (at {mot.param}={w.get('gap_at', 0):g})."
        checks.append(check(f"sweep:{a}|{b}", f"{a} ↔ {b}: clear through the cycle", st, "verified",
                            value={"min_gap_mm": round(min(w["min_gap"], 99), 3), "max_overlap_mm3": round(w["max_overlap"], 4)},
                            detail=det + (f" Declared {f.kind} fit." if f else "")))
    travel = {}
    for n, tr in track.items():
        pts = np.array([t[0] for t in tr])
        span = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
        rot = max(_rotation_angle(tr[0][1], t[1]) for t in tr)
        travel[n] = {"translation_mm": round(span, 2), "rotation_deg": round(rot, 1)}
    summary = {"param": mot.param, "poses": len(values), "step": mot.step, "travel": travel, "frames": frames,
               "start": mot.start, "stop": mot.stop, "deforming": sorted(deforming)}
    (proj.build_dir / "motion" / "poses.json").write_text(json.dumps({"param": mot.param, "step": mot.step, "poses": poses,
                                                                      "deforming": sorted(deforming)}))
    moving = {n: t for n, t in travel.items() if t["translation_mm"] > 0.05 or t["rotation_deg"] > 0.5}
    if mot.min_travel_mm or mot.min_travel_deg:
        for n, t in moving.items():
            if n in mot.exclude_travel:
                continue
            ok = t["translation_mm"] >= mot.min_travel_mm or t["rotation_deg"] >= mot.min_travel_deg
            checks.append(check(f"travel:{n}", f"{n}: visible motion", "pass" if ok else "warn", "measured",
                                value=t, limit={"mm": mot.min_travel_mm, "deg": mot.min_travel_deg},
                                detail="Centroid travel and rotation over one cycle."))
    return checks, summary
