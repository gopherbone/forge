"""Build stage: run design.py, validate solids, export STEP/STL in part, assembly and
print frames, and write the manifest that every later stage is stamped against."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

from .config import ForgeError
from .project import Project, now, sha

DIRS = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}


def rot(euler_deg) -> np.ndarray:
    return Rotation.from_euler("xyz", euler_deg or (0, 0, 0), degrees=True).as_matrix()


def placement_matrix(placement) -> np.ndarray:
    if placement and len(placement) == 2 and hasattr(placement[0], "__len__"):
        t, e = placement
    else:
        t, e = placement or (0, 0, 0), (0, 0, 0)
    M = np.eye(4)
    M[:3, :3] = rot(e)
    M[:3, 3] = t
    return M


def occ_transform(shape, M: np.ndarray):
    from build123d import Location
    from OCP.gp import gp_Trsf
    t = gp_Trsf()
    t.SetValues(*M[0, :4], *M[1, :4], *M[2, :4])
    return shape.moved(Location(t))


def to_print_frame(mesh: trimesh.Trimesh, euler_deg, bed_xy=(256, 256)) -> tuple[trimesh.Trimesh, np.ndarray]:
    """Rotate onto the bed, drop to z=0, center on the plate. Returns mesh and 4x4."""
    m = mesh.copy()
    M = np.eye(4)
    M[:3, :3] = rot(euler_deg)
    m.apply_transform(M)
    lo, hi = m.bounds
    T = np.eye(4)
    T[:3, 3] = [bed_xy[0] / 2 - (lo[0] + hi[0]) / 2, bed_xy[1] / 2 - (lo[1] + hi[1]) / 2, -lo[2]]
    m.apply_transform(T)
    return m, T @ M


def load_mesh(path: Path) -> trimesh.Trimesh:
    m = trimesh.load_mesh(path, process=True)
    if isinstance(m, trimesh.Scene):
        m = trimesh.util.concatenate(list(m.geometry.values()))
    return m


def build(proj: Project) -> dict:
    from build123d import export_step, export_stl

    proj.require()
    design = proj.load_design()
    out = proj.build_dir
    (out / "parts").mkdir(parents=True, exist_ok=True)
    (out / "assembly").mkdir(parents=True, exist_ok=True)
    names = [p.name for p in design.parts]
    if len(set(names)) != len(names):
        raise ForgeError(f"Duplicate part names: {names}")

    parts = {}
    problems = []
    for p in design.parts:
        shape = p.shape
        if hasattr(shape, "part"):  # BuildPart context
            shape = shape.part
        solids = shape.solids()
        if not solids:
            raise ForgeError(f"Part {p.name!r} has no solids")
        if not shape.is_valid:
            problems.append(f"{p.name}: OCC reports an invalid solid (self-intersection or bad boolean)")
        step = out / "parts" / f"{p.name}.step"
        stl = out / "parts" / f"{p.name}.stl"
        export_step(shape, step, timestamp="2000-01-01T00:00:00")
        export_stl(shape, stl, tolerance=0.005, angular_tolerance=0.08)
        M = placement_matrix(p.placement)
        placed = occ_transform(shape, M)
        pstep = out / "assembly" / f"{p.name}.step"
        pstl = out / "assembly" / f"{p.name}.stl"
        export_step(placed, pstep, timestamp="2000-01-01T00:00:00")
        export_stl(placed, pstl, tolerance=0.005, angular_tolerance=0.08)
        bb = shape.bounding_box()
        for c in p.cosmetic:
            if c not in DIRS:
                raise ForgeError(f"{p.name}: cosmetic direction {c!r} must be one of {list(DIRS)}")
        parts[p.name] = {
            "hash": sha(stl.read_bytes()),
            "material": p.material, "color": p.color, "cosmetic": list(p.cosmetic),
            "orient": list(p.orient) if p.orient is not None else None,
            "supports": p.supports, "bodies": p.bodies, "purchased": p.purchased, "placement_matrix": M.tolist(),
            "volume_mm3": round(shape.volume, 3), "n_solids": len(solids),
            "bbox_mm": [round(bb.size.X, 3), round(bb.size.Y, 3), round(bb.size.Z, 3)],
            "step": str(step.relative_to(proj.dir)), "stl": str(stl.relative_to(proj.dir)),
            "placed_step": str(pstep.relative_to(proj.dir)), "placed_stl": str(pstl.relative_to(proj.dir)),
            "notes": p.notes,
        }
    src = proj.source_hash()
    manifest = {
        "project": proj.name, "at": now(), "source_hash": src,
        "build_hash": sha((src + "".join(v["hash"] for v in parts.values())).encode()),
        "parts": parts, "design": design.describe(), "explode": design.explode,
        "problems": problems,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    proj.save("build", {"status": "fail" if problems else "pass", "problems": problems,
                        "parts": {k: {"volume_mm3": v["volume_mm3"], "bbox_mm": v["bbox_mm"]} for k, v in parts.items()}})
    return manifest


def print_orientation(proj: Project, part: str) -> tuple[list[float], str]:
    """Locked orientation from design.py wins; else the orient stage's pick; else as-modelled."""
    m = proj.manifest()["parts"][part]
    if m["orient"] is not None:
        return m["orient"], "locked in design"
    r = proj.result("orient")
    if r and not proj.stale("orient") and part in r.get("parts", {}):
        return r["parts"][part]["best"]["euler"], "chosen by forge orient"
    return [0, 0, 0], "as modelled (orient not run)"
