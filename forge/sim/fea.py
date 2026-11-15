"""Static FEA with gmsh (quadratic tets) + CalculiX.

- Linear or geometrically nonlinear (NLGEOM) static, force- or displacement-controlled.
- Displacement control gives a force-deflection curve: the right tool for snap fits,
  clips and flexures ("how hard is it to push, and does it survive?").
- Strength is checked in the PRINT frame: stress across layers (build Z) is compared
  with the much lower interlayer strength. That ties the result to print orientation.

Honest limits (also printed in reports):
- Isotropic linear-elastic material (xy modulus). No plasticity, creep or fatigue.
- Infill is not modelled: the part is treated as 100% solid. Thin flexures should be
  printed with enough walls to be solid in practice (forge slice checks wall count).
- Peak stresses next to fixed regions are inflated by the rigid boundary condition,
  so headline numbers exclude nodes inside the fixed region.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import config
from ..dsl import LoadCase, select

# gmsh tet10 -> CalculiX C3D10 node order (gmsh's last two edge nodes are swapped).
# CalculiX C3D10 order matches VTK_QUADRATIC_TETRA, which the renderer relies on.
GMSH_TO_CCX = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]


@dataclass
class Mesh:
    nodes: np.ndarray  # (N,3)
    tets: np.ndarray   # (M,10), 0-based, CalculiX order
    size: float


def mesh_step(step: Path, size: float, refine=None, coarse: float | None = None) -> Mesh:
    """Quadratic tet mesh. With `refine` (Region or list of Regions), elements are `size`
    inside those boxes and grow to `coarse` outside, so the mesh is fine only where it matters."""
    import gmsh
    gmsh.initialize(["-noenv"])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("part")
        gmsh.model.occ.importShapes(str(step))
        gmsh.model.occ.synchronize()
        if refine is not None:
            coarse = coarse or max(3 * size, 2.5)
            boxes = [refine] if hasattr(refine, "min") else list(refine)
            fids = []
            for r in boxes:
                f = gmsh.model.mesh.field.add("Box")
                gmsh.model.mesh.field.setNumber(f, "VIn", size)
                gmsh.model.mesh.field.setNumber(f, "VOut", coarse)
                for k, v in zip(("XMin", "YMin", "ZMin"), r.min):
                    gmsh.model.mesh.field.setNumber(f, k, v)
                for k, v in zip(("XMax", "YMax", "ZMax"), r.max):
                    gmsh.model.mesh.field.setNumber(f, k, v)
                gmsh.model.mesh.field.setNumber(f, "Thickness", 3 * coarse)
                fids.append(f)
            fm = gmsh.model.mesh.field.add("Min")
            gmsh.model.mesh.field.setNumbers(fm, "FieldsList", fids)
            gmsh.model.mesh.field.setAsBackgroundMesh(fm)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
            gmsh.option.setNumber("Mesh.MeshSizeMax", coarse)
            gmsh.option.setNumber("Mesh.MeshSizeMin", size / 2)
        else:
            gmsh.option.setNumber("Mesh.MeshSizeMax", size)
            gmsh.option.setNumber("Mesh.MeshSizeMin", size / 5)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 16)
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.model.mesh.generate(3)
        tags, coords, _ = gmsh.model.mesh.getNodes()
        etypes, _, enodes = gmsh.model.mesh.getElements(dim=3)
        if 11 not in list(etypes):
            raise config.ForgeError("gmsh produced no quadratic tetrahedra (is the STEP a closed solid?)")
        conn = np.asarray(enodes[list(etypes).index(11)], dtype=np.int64).reshape(-1, 10)
    finally:
        gmsh.finalize()
    order = np.argsort(tags)
    tags = np.asarray(tags)[order]
    xyz = np.asarray(coords).reshape(-1, 3)[order]
    idx = np.searchsorted(tags, conn)
    return Mesh(nodes=xyz, tets=idx[:, GMSH_TO_CCX], size=size)


def write_deck(path: Path, mesh: Mesh, lc: LoadCase, mat: dict, fix_ids, load_ids) -> None:
    L = []
    L.append("*HEADING\nforge " + lc.name)
    L.append("*NODE, NSET=NALL")
    L += [f"{i + 1}, {x:.6f}, {y:.6f}, {z:.6f}" for i, (x, y, z) in enumerate(mesh.nodes)]
    ref = len(mesh.nodes) + 1
    c = mesh.nodes[load_ids].mean(axis=0)
    L.append(f"{ref}, {c[0]:.6f}, {c[1]:.6f}, {c[2]:.6f}")
    L.append("*ELEMENT, TYPE=C3D10, ELSET=EALL")
    L += [f"{e + 1}, " + ", ".join(str(n + 1) for n in t) for e, t in enumerate(mesh.tets)]

    def nset(name, ids):
        L.append(f"*NSET, NSET={name}")
        ids = [str(i + 1) for i in ids]
        L.extend(", ".join(ids[k:k + 12]) for k in range(0, len(ids), 12))

    nset("FIX", fix_ids)
    nset("LOAD", load_ids)
    L.append(f"*NSET, NSET=REF\n{ref}")
    L.append(f"*MATERIAL, NAME=M\n*ELASTIC\n{mat['E_mpa']}, {mat['poisson']}")
    L.append("*SOLID SECTION, ELSET=EALL, MATERIAL=M")
    if lc.displacement is not None:  # coupling equations belong in the model definition
        n = len(load_ids)
        for dof, v in enumerate(lc.displacement, start=1):
            if abs(v) > 0:
                L.append(f"*EQUATION\n{n + 1}")
                terms = [f"{i + 1}, {dof}, 1.0" for i in load_ids] + [f"{ref}, {dof}, {-float(n)}"]
                L.extend(", ".join(terms[k:k + 4]) + "," * (k + 4 < len(terms)) for k in range(0, len(terms), 4))
    inc = 1.0 / max(1, lc.steps)
    if lc.nonlinear:
        L.append("*STEP, NLGEOM, INC=1000")
        L.append(f"*STATIC\n{inc}, 1.0, {inc / 1000:.3e}, {inc}")
    else:
        L.append("*STEP\n*STATIC")
    L.append("*BOUNDARY\nFIX, 1, 3, 0.0")
    if lc.displacement is not None:
        # Distributing coupling: a reference node carries the prescribed displacement and an
        # *EQUATION ties it to the AVERAGE displacement of the contact nodes, so the loaded
        # area can still rotate. Prescribing every contact node directly locks rotation
        # (a guided beam): 2.8x too stiff on the bare-cantilever control.
        for dof, v in enumerate(lc.displacement, start=1):
            L.append(f"*BOUNDARY\nREF, {dof}, {dof}, {v if abs(v) > 0 else 0.0}")
    if lc.force is not None:
        L.append("*CLOAD")
        n = len(load_ids)
        for i in load_ids:
            for dof, v in enumerate(lc.force, start=1):
                if abs(v) > 0:
                    L.append(f"{i + 1}, {dof}, {v / n:.8e}")
    # field output only at the end of the step (FREQUENCY beyond the increment count)
    L.append("*NODE FILE, FREQUENCY=100000\nU\n*EL FILE, FREQUENCY=100000\nS, E")
    rf_set = "REF" if lc.displacement is not None else "LOAD"
    L.append(f"*NODE PRINT, NSET={rf_set}, TOTALS=ONLY, FREQUENCY=1\nRF")
    L.append("*NODE PRINT, NSET=FIX, TOTALS=ONLY, FREQUENCY=1\nRF")
    L.append("*NODE PRINT, NSET=LOAD, FREQUENCY=1\nU")
    L.append("*END STEP")
    path.write_text("\n".join(L) + "\n")


def run_ccx(deck: Path, timeout=1800) -> str:
    job = deck.with_suffix("")
    p = subprocess.run([str(config.ccx_path()), "-i", job.name], cwd=deck.parent, capture_output=True,
                       text=True, timeout=timeout, env={"OMP_NUM_THREADS": "8", "PATH": "/usr/bin:/bin"})
    log = p.stdout + p.stderr
    (deck.parent / f"{job.name}.log").write_text(log)
    if p.returncode != 0 or "*ERROR" in log:
        tail = "\n".join(l for l in log.splitlines() if "ERROR" in l or "error" in l)[-1500:]
        raise config.ForgeError(f"CalculiX failed for {deck.name}:\n{tail or log[-1500:]}")
    return log


_num = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"


def parse_dat(dat: Path) -> dict:
    """Per-increment totals: {'time': [...], 'rf_load': [[fx,fy,fz]...], 'rf_fix': [...], 'u_load': [[ux,uy,uz]...]}"""
    out = {"time": [], "rf_load": [], "rf_fix": [], "u_load": []}
    lines = dat.read_text().splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = re.search(r"total force \(fx,fy,fz\) for set (\w+) and time\s+(" + _num + ")", ln)
        if m:
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            vals = [float(v) for v in re.findall(_num, lines[j])][:3]
            if m.group(1).upper() in ("LOAD", "REF"):
                out["rf_load"].append(vals)
                out["time"].append(float(m.group(2)))
            else:
                out["rf_fix"].append(vals)
            i = j + 1
            continue
        m = re.search(r"displacements \(vx,vy,vz\) for set LOAD and time", ln)
        if m:
            j = i + 1
            rows = []
            while j < len(lines) and not lines[j].strip():
                j += 1
            while j < len(lines) and lines[j].strip() and re.match(r"^\s*\d+\s", lines[j]):
                rows.append([float(v) for v in re.findall(_num, lines[j])[1:4]])
                j += 1
            out["u_load"].append(np.mean(rows, axis=0).tolist() if rows else [0, 0, 0])
            i = j
            continue
        i += 1
    return out


def parse_frd(frd: Path, n_nodes: int) -> dict[str, np.ndarray]:
    """Last block of DISP / STRESS / TOSTRAIN as (N, k) arrays indexed by node-1."""
    blocks: dict[str, np.ndarray] = {}
    cur = None
    arr = None
    with frd.open() as f:
        for ln in f:
            if ln.startswith(" -4"):
                name = ln[5:13].strip()
                cur = name if name in ("DISP", "STRESS", "TOSTRAIN") else None
                if cur:
                    k = 3 if cur == "DISP" else 6
                    arr = np.zeros((n_nodes, k))
            elif cur and ln.startswith(" -1"):
                nid = int(ln[3:13])
                if nid > n_nodes:  # coupling reference node
                    continue
                k = arr.shape[1]
                vals = [float(ln[13 + 12 * c: 25 + 12 * c]) for c in range(k)]
                arr[nid - 1] = vals
            elif cur and ln.startswith(" -3"):
                blocks[cur] = arr
                cur = None
    return blocks


def tensor(v6: np.ndarray) -> np.ndarray:
    """(N,6) xx yy zz xy yz zx -> (N,3,3)"""
    T = np.zeros((len(v6), 3, 3))
    T[:, 0, 0], T[:, 1, 1], T[:, 2, 2] = v6[:, 0], v6[:, 1], v6[:, 2]
    T[:, 0, 1] = T[:, 1, 0] = v6[:, 3]
    T[:, 1, 2] = T[:, 2, 1] = v6[:, 4]
    T[:, 2, 0] = T[:, 0, 2] = v6[:, 5]
    return T


def von_mises(s: np.ndarray) -> np.ndarray:
    xx, yy, zz, xy, yz, zx = s.T
    return np.sqrt(0.5 * ((xx - yy) ** 2 + (yy - zz) ** 2 + (zz - xx) ** 2) + 3 * (xy ** 2 + yz ** 2 + zx ** 2))


def evaluate(field: dict, R: np.ndarray, mat: dict, use: str, exclude: np.ndarray) -> dict:
    """Safety factors / strain utilisation for a print orientation R (part -> print frame)."""
    keep = ~exclude if (~exclude).any() else np.ones_like(exclude)
    S = tensor(field["S"])[keep]
    E = tensor(field["E"])[keep]
    vm = von_mises(field["S"][keep])
    Sb = np.einsum("ij,njk,lk->nil", R, S, R)
    Eb = np.einsum("ij,njk,lk->nil", R, E, R)
    s_zz = Sb[:, 2, 2]
    e1 = np.linalg.eigvalsh(E)[:, -1]
    e_zz = Eb[:, 2, 2]
    vm_max = float(vm.max())
    szz_max = float(max(s_zz.max(), 0.0))
    sf_xy = mat["strength_xy_mpa"] / vm_max if vm_max > 0 else float("inf")
    sf_z = mat["strength_z_mpa"] / szz_max if szz_max > 0 else float("inf")
    out = {
        "von_mises_max_mpa": round(vm_max, 3),
        "von_mises_p99_mpa": round(float(np.percentile(vm, 99)), 3),
        "interlayer_tension_max_mpa": round(szz_max, 3),
        "sf_xy": round(sf_xy, 2), "sf_z": round(sf_z, 2), "sf": round(min(sf_xy, sf_z), 2),
        "governing": "layer adhesion (Z)" if sf_z < sf_xy else "in-layer strength (XY)",
        "strain_max": round(float(e1.max()), 5),
        "strain_z_max": round(float(max(e_zz.max(), 0)), 5),
    }
    if use in ("once", "repeated"):
        allow = mat["strain_allow_once" if use == "once" else "strain_allow_repeated"]
        allow_z = allow * mat["strain_allow_z_factor"]
        out["strain_allow"] = allow
        out["strain_allow_z"] = round(allow_z, 5)
        out["strain_util"] = round(max(out["strain_max"] / allow, out["strain_z_max"] / allow_z), 3)
    return out


def grow(r, d: float):
    from ..dsl import Region
    rs = [r] if hasattr(r, "min") else list(r)
    return [Region(tuple(v - d for v in x.min), tuple(v + d for v in x.max)) for x in rs]


def auto_mesh_size(bbox, thin: float | None) -> float:
    s = 0.6 * thin if thin and np.isfinite(thin) else min(bbox) / 4
    return float(np.clip(s, 0.35, 3.0))


def solve(step: Path, lc: LoadCase, mat: dict, workdir: Path, size: float, refine=None, coarse=None) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    mesh = mesh_step(step, size, refine, coarse)
    corner = np.unique(mesh.tets[:, :4])
    fix = np.nonzero(select(lc.fixed, mesh.nodes))[0]
    load = np.nonzero(select(lc.load, mesh.nodes))[0]
    if len(fix) == 0 or len(load) == 0:
        raise config.ForgeError(f"Load case {lc.name}: region selects no nodes "
                                f"(fixed: {len(fix)}, load: {len(load)}). Check Region boxes are in the part frame.")
    if lc.force is None and lc.displacement is None:
        raise config.ForgeError(f"Load case {lc.name}: give force or displacement")
    deck = workdir / f"{lc.name}.inp"
    write_deck(deck, mesh, lc, mat, fix, load)
    run_ccx(deck)
    dat = parse_dat(deck.with_suffix(".dat"))
    fld = parse_frd(deck.with_suffix(".frd"), len(mesh.nodes))
    if "STRESS" not in fld:
        raise config.ForgeError(f"{lc.name}: no stress output in .frd")
    from scipy.spatial import cKDTree
    fixed_m, load_m = select(lc.fixed, mesh.nodes), select(lc.load, mesh.nodes)
    # Nodes next to a point/line load or inside a rigid support carry artificial peaks
    # (St Venant). Headline numbers exclude them: within max(1 mm, 2 elements) of loaded nodes.
    near_load = cKDTree(mesh.nodes[load_m]).query(mesh.nodes)[0] < max(1.0, 2 * size)
    field = {"nodes": mesh.nodes, "tets": mesh.tets, "U": fld["DISP"], "S": fld["STRESS"], "E": fld["TOSTRAIN"],
             "fixed": fixed_m, "load": load_m, "exclude": fixed_m | near_load}
    np.savez_compressed(workdir / f"{lc.name}.npz", **field)
    # force-deflection along the load direction
    if lc.displacement is not None:
        d = np.asarray(lc.displacement, float)
        rf = -np.asarray(dat["rf_fix"])  # equilibrium: CalculiX reports no RF on a coupling-only node
    else:
        d = np.asarray(lc.force, float)
        rf = -np.asarray(dat["rf_fix"])  # reaction at the support balances the applied load
    dirn = d / np.linalg.norm(d)
    u = np.asarray(dat["u_load"]) @ dirn if dat["u_load"] else np.zeros(len(rf))
    f = rf @ dirn if len(rf) else np.zeros(0)
    curve = [[0.0, 0.0]] + [[round(float(a), 5), round(float(b), 5)] for a, b in zip(u, f)]
    cv = np.asarray(curve)
    energy_mj = float(np.trapezoid(np.abs(cv[:, 1]), np.abs(cv[:, 0]))) if len(cv) > 1 else 0.0  # N·mm = mJ
    return {
        "mesh": {"size_mm": round(size, 3), "refined": refine is not None, "nodes": int(len(mesh.nodes)), "elements": int(len(mesh.tets)),
                 "corner_nodes": int(len(corner)), "fixed_nodes": int(len(fix)), "load_nodes": int(len(load))},
        "curve": curve,
        "disp_max_mm": round(float(np.linalg.norm(fld["DISP"], axis=1).max()), 4),
        "load_disp_mm": round(float(u[-1]) if len(u) else 0.0, 4),
        "load_force_n": round(float(f[-1]) if len(f) else 0.0, 4),
        "energy_mj": round(energy_mj, 4),  # stored elastic energy (area under the force-deflection curve)
        "_field": field,
    }
