"""Print-orientation search.

Candidates: the 6 axis-aligned poses + the mesh's physically stable resting poses.
Each one is scored on support area, height (time), bed contact, show faces touching
supports, and, if a current FEA field exists, strength across layers (the same
stress field rotated into each candidate's build frame, no re-solve needed)."""
from __future__ import annotations

import warnings

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

from . import config
from .checks.printability import BED, SUPPORT, classify_faces
from .geometry import DIRS, rot, to_print_frame
from .printer import Printer

AXIS_POSES = {"as modelled": (0, 0, 0), "on +x face": (0, 90, 0), "on -x face": (0, -90, 0),
              "on -y face": (90, 0, 0), "on +y face": (-90, 0, 0), "upside down": (180, 0, 0)}

W = {"support": 12.0, "height": 1.0, "contact": 2.0, "cosmetic": 4.0, "strength": 6.0}


def candidates(mesh: trimesh.Trimesh) -> list[tuple[str, tuple]]:
    out = list(AXIS_POSES.items())
    try:
        T, prob = trimesh.poses.compute_stable_poses(mesh, n_samples=1, threshold=0.02)
        for i, (t, p) in enumerate(zip(T[:6], prob[:6])):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                e = Rotation.from_matrix(t[:3, :3]).as_euler("xyz", degrees=True)
            out.append((f"stable pose {i + 1} ({p:.0%})", tuple(np.round(e, 2))))
    except Exception:
        pass
    # dedupe on which part-frame direction ends up pointing down
    seen, uniq = [], []
    for name, e in out:
        down = rot(e).T @ np.array([0, 0, -1.0])
        if any(np.dot(down, s) > 0.995 for s in seen):
            continue
        seen.append(down)
        uniq.append((name, e))
    return uniq


def score(mesh: trimesh.Trimesh, euler, printer: Printer, meta: dict, fields: list | None = None) -> dict:
    rules = config.rules()
    m, _ = to_print_frame(mesh, euler, printer.bed_xy)
    cls, _ = classify_faces(m, printer, rules)
    area = m.area_faces
    total = float(area.sum())
    sup = float(area[cls == SUPPORT].sum())
    contact = float(area[cls == BED].sum())
    h = float(m.extents[2])
    R = rot(euler)
    cos_hits = 0
    for c in meta.get("cosmetic", []):
        v = R @ np.asarray(DIRS[c], float)
        faces = m.face_normals @ v > 0.9
        cos_hits += int((cls[faces] == SUPPORT).any())
    out = {"euler": [float(x) for x in euler], "support_mm2": round(sup, 1), "height_mm": round(h, 1),
           "contact_mm2": round(contact, 1), "cosmetic_on_support": cos_hits}
    s = (W["support"] * sup / total + W["height"] * h / max(mesh.extents)
         - W["contact"] * min(contact / max(total * 0.15, 1e-9), 1.0) + W["cosmetic"] * cos_hits)
    if fields:
        from .sim.fea import evaluate
        sfs = []
        for f, mat, use in fields:
            ev = evaluate(f, R, mat, use, f.get("exclude", f["fixed"]))
            sfs.append(ev["sf"])
            if "strain_util" in ev:
                sfs.append(1.0 / max(ev["strain_util"], 1e-9))
        sf = min(sfs)
        target = fields[0][1]["safety_factor_target"]
        out["sf_min"] = round(sf, 2)
        s += W["strength"] * max(0.0, target / max(sf, 1e-6) - 1.0)
    out["score"] = round(float(s), 3)
    return out


def search(mesh, printer, meta, fields=None) -> list[dict]:
    rows = []
    for name, e in candidates(mesh):
        r = score(mesh, e, printer, meta, fields)
        r["name"] = name
        rows.append(r)
    return sorted(rows, key=lambda r: r["score"])
