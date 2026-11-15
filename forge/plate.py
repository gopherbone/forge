"""Read the sliced Bambu 3MF plates back into meshes placed exactly where the slicer
arranged them, for studio's plate view. Standard-library XML; no lxml needed.

Bambu 3MF layout: 3D/3dmodel.model has <object id> entries with <components> pointing at
3D/Objects/object_N.model meshes (each with a transform), and <build><item objectid
transform> placements on the plate. Metadata/model_settings.config maps object ids to the
source STL names (our part names)."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np

from .project import Project

NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
PNS = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"


def _T(s: str | None) -> np.ndarray:
    M = np.eye(4)
    if s:
        v = [float(x) for x in s.split()]
        M[:3, :3] = np.array(v[:9]).reshape(3, 3).T  # 3MF: row vectors, m00 m01 m02 m10 ...
        M[:3, 3] = v[9:12]
    return M


def _mesh(root, oid: str):
    for obj in root.iter(f"{{{NS['m']}}}object"):
        if obj.get("id") == oid:
            mesh = obj.find("m:mesh", NS)
            if mesh is None:
                return None
            V = np.array([[float(v.get(a)) for a in "xyz"] for v in mesh.find("m:vertices", NS)])
            F = np.array([[int(t.get(a)) for a in ("v1", "v2", "v3")] for t in mesh.find("m:triangles", NS)])
            return V, F
    return None


def read_plate(path: Path) -> list[dict]:
    import trimesh
    out = []
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("3D/3dmodel.model"))
        names = {}
        try:
            cfg = z.read("Metadata/model_settings.config").decode()
            for m in re.finditer(r'<object id="(\d+)">(.*?)</object>', cfg, re.S):
                src = re.search(r'key="source_file" value="([^"]+)"', m.group(2))
                if src:
                    names[m.group(1)] = Path(src.group(1)).stem
        except KeyError:
            pass
        subs = {}
        for item in root.find("m:build", NS):
            oid = item.get("objectid")
            Ti = _T(item.get("transform"))
            obj = next(o for o in root.iter(f"{{{NS['m']}}}object") if o.get("id") == oid)
            parts = []
            comps = obj.find("m:components", NS)
            if comps is not None:
                for c in comps:
                    p = c.get(f"{PNS}path")
                    sub_root = root
                    if p:
                        p = p.lstrip("/")
                        if p not in subs:
                            subs[p] = ET.fromstring(z.read(p))
                        sub_root = subs[p]
                    mv = _mesh(sub_root, c.get("objectid"))
                    if mv:
                        parts.append((mv, _T(c.get("transform"))))
            else:
                mv = _mesh(root, oid)
                if mv:
                    parts.append((mv, np.eye(4)))
            meshes = []
            for (V, F), Tc in parts:
                m = trimesh.Trimesh(V, F, process=False)
                m.apply_transform(Ti @ Tc)
                meshes.append(m)
            if meshes:
                out.append({"name": names.get(oid, f"object_{oid}"), "mesh": trimesh.util.concatenate(meshes)})
    return out


def extract(proj: Project) -> list[dict]:
    """Write build/plate/<plate>/<part>.stl from each sliced 3MF, and build/plate/plates.json."""
    sl = proj.result("slice") or {}
    base = proj.build_dir / "plate"
    plates = []
    for p in sl.get("plates", []):
        if not p.get("threemf"):
            continue
        d = base / p["name"]
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.stl"):
            old.unlink()
        items = []
        for it in read_plate(proj.dir / p["threemf"]):
            f = d / f"{it['name']}.stl"
            it["mesh"].export(f)
            items.append({"name": it["name"], "stl": str(f.relative_to(proj.dir))})
        plates.append({"name": p["name"], "material": p.get("material"), "support": p.get("support"),
                       "time": p["stats"].get("time_str"), "grams": p["stats"].get("filament_g"), "items": items,
                       "bed": p["stats"].get("settings", {}).get("bed_mm", [256, 256, 250])})
    (base).mkdir(parents=True, exist_ok=True)
    (base / "plates.json").write_text(json.dumps({"plates": plates}))
    return plates
