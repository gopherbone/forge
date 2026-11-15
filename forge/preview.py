"""Fast, isolated geometry preview for forge studio's hot reload.

    forge preview <project>

Runs design.py with the spec params and exports each part's mesh (part frame, coarse
tessellation) plus its placement matrix to build/preview/. It never touches the
manifest or any stage result, so it can run while an agent works, and a broken
design.py produces an error record instead of a build."""
from __future__ import annotations

import json
import time
import traceback

from .geometry import placement_matrix
from .project import Project


def preview(proj: Project) -> dict:
    from build123d import export_stl

    out = proj.build_dir / "preview"
    out.mkdir(parents=True, exist_ok=True)
    rec = {"at": time.time(), "source_hash": proj.source_hash(), "parts": [], "error": None}
    t0 = time.time()
    try:
        d = proj.load_design()
        keep = set()
        for p in d.parts:
            s = p.shape.part if hasattr(p.shape, "part") else p.shape
            f = out / f"{p.name}.stl"
            export_stl(s, f, tolerance=0.03, angular_tolerance=0.2)
            keep.add(f.name)
            bb = s.bounding_box()
            rec["parts"].append({"name": p.name, "color": p.color, "stl": f"build/preview/{p.name}.stl",
                                 "M": sum(placement_matrix(p.placement).tolist(), []),
                                 "bbox": [round(bb.size.X, 2), round(bb.size.Y, 2), round(bb.size.Z, 2)],
                                 "volume": round(s.volume / 1000, 3), "material": p.material, "notes": p.notes})
        for old in out.glob("*.stl"):
            if old.name not in keep:
                old.unlink()
        rec["motion"] = {"param": d.motion.param} if d.motion else None
    except Exception as e:  # show the agent's broken state instead of hiding it
        tb = traceback.format_exc().splitlines()
        rec["error"] = {"type": type(e).__name__, "message": str(e)[:400], "trace": "\n".join(tb[-8:])}
    rec["seconds"] = round(time.time() - t0, 2)
    (out / "preview.json").write_text(json.dumps(rec))
    return rec
