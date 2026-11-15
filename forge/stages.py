"""Pipeline stages. Each one reads the manifest, does one job, and writes a stamped
result. `run_all` chains them: build → orient → check → fit → sim → orient(again, now
strength-aware) → slice → render → report."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

from . import config, geometry, orient as orient_mod, printer as printer_mod, slicer
from .checks import assembly, printability, worst
from .dsl import LoadCase, Region
from .project import Project
from .sim import fea


def _current(proj: Project) -> None:
    """Refuse to compute results from an outdated build (design, spec or forge data changed)."""
    if proj.source_hash() != proj.manifest()["source_hash"]:
        raise config.ForgeError(f"{proj.name}: design.py, spec.yaml or forge/data changed since the last build. "
                                f"Run `forge build {proj.name}` (or `forge run {proj.name}`) first.")


def _printer(proj: Project, part: str | None = None):
    m = proj.manifest()
    mat = m["parts"][part]["material"] if part else next(iter(m["parts"].values()))["material"]
    return printer_mod.load(proj.spec.get("printer"), mat)


def _loadcases(proj: Project) -> list[LoadCase]:
    out = []
    for d in proj.manifest()["design"]["loads"]:
        d = dict(d)
        for k in ("fixed", "load", "refine"):
            if d.get(k) is not None:
                d[k] = [Region(**r) for r in d[k]] if isinstance(d[k], list) else Region(**d[k])
        for k in ("force", "displacement"):
            if d.get(k) is not None:
                d[k] = tuple(d[k])
        out.append(LoadCase(**d))
    return out


def _fits(proj: Project):
    from .dsl import Fit
    out = []
    for d in proj.manifest()["design"]["fits"]:
        d = dict(d)
        if d.get("region"):
            d["region"] = Region(**d["region"])
        out.append(Fit(**d))
    return out


# ---------------------------------------------------------------- build
def build(proj: Project) -> dict:
    m = geometry.build(proj)
    return proj.result("build") | {"manifest": m}


# ---------------------------------------------------------------- orient
def _sim_fields(proj: Project, part: str):
    r = proj.result("sim")
    if not r or proj.stale("sim"):
        return None
    fields = []
    for lc in r.get("cases", []):
        if lc["part"] != part or "npz" not in lc:
            continue
        p = proj.dir / lc["npz"]
        if p.exists():
            z = np.load(p)
            fields.append(({k: z[k] for k in z.files}, config.material(lc["material"]), lc["use"]))
    return fields or None


def orient(proj: Project) -> dict:
    _current(proj)
    m = proj.manifest()
    out = {}
    for name, meta in m["parts"].items():
        if meta.get("purchased"):
            continue
        pr = _printer(proj, name)
        mesh = geometry.load_mesh(proj.dir / meta["stl"])
        fields = _sim_fields(proj, name)
        rows = orient_mod.search(mesh, pr, meta, fields)
        out[name] = {"best": rows[0], "candidates": rows, "locked": meta["orient"],
                     "strength_aware": fields is not None}
    proj.save("orient", {"status": "pass", "parts": out})
    return out


# ---------------------------------------------------------------- check
def check(proj: Project) -> dict:
    _current(proj)
    m = proj.manifest()
    # never check a pose nobody chose: refresh the orientation search if it is stale
    if any(v["orient"] is None for v in m["parts"].values()) and proj.stale("orient"):
        orient(proj)
    (proj.build_dir / "print").mkdir(parents=True, exist_ok=True)
    parts, statuses = {}, []
    for name, meta in m["parts"].items():
        if meta.get("purchased"):
            parts[name] = {"status": "info", "purchased": True, "checks": [], "orientation": {"euler": [0, 0, 0], "source": "purchased"}}
            continue
        pr = _printer(proj, name)
        euler, why = geometry.print_orientation(proj, name)
        mesh = geometry.load_mesh(proj.dir / meta["stl"])
        pm, M = geometry.to_print_frame(mesh, euler, pr.bed_xy)
        stl = proj.build_dir / "print" / f"{name}.stl"
        pm.export(stl)
        checks, extra = printability.analyze(pm, pr, meta, euler)
        from .checks import features
        fit_parts = any(name in (f["a"], f["b"]) and f["kind"] in ("snug", "sliding", "loose", "press")
                        for f in m["design"]["fits"])
        checks += features.analyze(proj.dir / meta["step"], geometry.rot(euler), pm, pr, config.rules(), fit_parts)
        npz = proj.results_dir / f"check_{name}.npz"
        proj.results_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(npz, face_class=extra["face_class"], th_points=extra["thickness"]["points"],
                            th=extra["thickness"]["t"])
        st = worst(checks)
        statuses.append(st)
        parts[name] = {"status": st, "orientation": {"euler": euler, "source": why, "matrix": M.tolist()},
                       "print_stl": str(stl.relative_to(proj.dir)), "npz": str(npz.relative_to(proj.dir)),
                       "checks": checks, "overhang_regions": extra["regions"], "printer": pr.summary()}
    r = {"status": worst([{"status": s} for s in statuses]), "parts": parts}
    proj.save("check", r)
    return r


# ---------------------------------------------------------------- fit
def fit(proj: Project) -> dict:
    _current(proj)
    from build123d import import_step
    m = proj.manifest()
    shapes = {n: import_step(proj.dir / v["placed_step"]) for n, v in m["parts"].items()}
    checks = assembly.run(shapes, _fits(proj)) if len(shapes) > 1 else []
    # snap-together construction (user rule): every joint must say how it stays together
    loads = {l["name"] for l in m["design"]["loads"]}
    for f in m["design"]["fits"]:
        if f["kind"] == "contact" and not f.get("retention"):
            continue
        ret, nm = f.get("retention"), f"{f['a']} ↔ {f['b']}: retention"
        if ret is None:
            checks.append({"id": f"ret:{f['a']}|{f['b']}", "name": nm, "status": "warn", "kind": "heuristic", "value": None,
                           "detail": "How does this joint stay together? Snap-together construction: declare retention "
                                     "(snap with a verified snap_case, captured by another part, or press)."})
        elif ret == "snap" and (not f.get("snap_case") or f["snap_case"] not in loads):
            checks.append({"id": f"ret:{f['a']}|{f['b']}", "name": nm, "status": "warn", "kind": "heuristic", "value": f.get("snap_case"),
                           "detail": "Snap declared, but no LoadCase verifies it (strain and the 5-15 N feel). Add one and name it in snap_case."})
        elif ret in ("gravity", "none"):
            checks.append({"id": f"ret:{f['a']}|{f['b']}", "name": nm, "status": "warn", "kind": "heuristic", "value": ret,
                           "detail": "Held only by gravity, so it falls apart when tipped. The user wants snap-together construction."})
        else:
            checks.append({"id": f"ret:{f['a']}|{f['b']}", "name": nm, "status": "pass", "kind": "heuristic", "value": ret,
                           "detail": f"Retained by: {ret}" + (f" (verified by load case {f['snap_case']})" if f.get("snap_case") else "")})
    motion = {}
    if m["design"].get("motion"):
        from . import motion as motion_mod
        sweep_checks, motion = motion_mod.sweep(proj)
        checks += sweep_checks
    r = {"status": worst(checks), "checks": checks, "calibrated": config.fits_calibrated(), "motion": motion}
    proj.save("fit", r)
    return r


# ---------------------------------------------------------------- sim
def sim(proj: Project, converge: bool = True, only: str | None = None) -> dict:
    _current(proj)
    m = proj.manifest()
    chk = proj.result("check") or {}
    cases, statuses = [], []
    for lc in _loadcases(proj):
        if only and lc.name != only:
            continue
        meta = m["parts"][lc.part]
        mat = config.material(meta["material"])
        thin = None
        try:
            wt = next(c for c in chk["parts"][lc.part]["checks"] if c["id"] == "wall_thickness")
            thin = max(wt["value"]["p2_mm"], 0.8)
        except Exception:
            pass
        size = lc.mesh_size or fea.auto_mesh_size(meta["bbox_mm"], thin)
        wd = proj.build_dir / "sim" / lc.name
        refine = None if lc.uniform else (lc.refine or fea.grow(lc.load, 8.0))
        r = fea.solve(proj.dir / meta["step"], lc, mat, wd, size, refine)
        euler, why = geometry.print_orientation(proj, lc.part)
        R = geometry.rot(euler)
        field = r.pop("_field")
        ev = fea.evaluate(field, R, mat, lc.use, field["exclude"])
        conv = None
        if converge:
            r2 = fea.solve(proj.dir / meta["step"], lc, mat, wd / "fine", size * 0.65, refine)
            f2 = r2.pop("_field")
            ev2 = fea.evaluate(f2, R, mat, lc.use, f2["exclude"])
            key = "strain_max" if lc.use != "static" else "von_mises_max_mpa"

            def rel(a, b):
                return abs(a - b) / max(abs(b), 1e-12)
            conv = {"fine_size_mm": round(size * 0.65, 3), "fine_elements": r2["mesh"]["elements"],
                    "delta_peak_pct": round(100 * rel(ev[key], ev2[key]), 1),
                    "delta_disp_pct": round(100 * rel(r["disp_max_mm"], r2["disp_max_mm"]), 1),
                    "delta_force_pct": round(100 * rel(r["load_force_n"], r2["load_force_n"]), 1) if r2["load_force_n"] else None,
                    "metric": key}
            # report the finer (more accurate) mesh
            r, field, ev = r2, f2, ev2
            shutil.copy(wd / "fine" / f"{lc.name}.npz", wd / f"{lc.name}.npz")
        target = mat["safety_factor_target"]
        checks = []
        if lc.use == "static":
            st = "pass" if ev["sf"] >= target else "warn" if ev["sf"] >= 1.0 else "fail"
            checks.append({"id": f"sf:{lc.name}", "name": f"{lc.name}: safety factor", "status": st, "kind": "estimated",
                           "value": ev["sf"], "limit": target,
                           "detail": f"Governed by {ev['governing']}. Peak von Mises {ev['von_mises_max_mpa']} MPa, "
                                     f"tension across layers {ev['interlayer_tension_max_mpa']} MPa."})
        else:
            u = ev["strain_util"]
            st = "pass" if u <= 0.8 else "warn" if u <= 1.0 else "fail"
            checks.append({"id": f"strain:{lc.name}", "name": f"{lc.name}: flex strain", "status": st, "kind": "estimated",
                           "value": u, "limit": 1.0,
                           "detail": f"Peak strain {100 * ev['strain_max']:.2f}% vs allowable {100 * ev['strain_allow']:.1f}% "
                                     f"({lc.use} use); across layers {100 * ev['strain_z_max']:.2f}% vs {100 * ev['strain_allow_z']:.1f}%."})
        if lc.min_force_n is not None or lc.max_force_n is not None:
            fz = abs(r["load_force_n"])
            lo, hi = lc.min_force_n or 0.0, lc.max_force_n or float("inf")
            fst = "pass" if lo <= fz <= hi else "fail"
            checks.append({"id": f"feel:{lc.name}", "name": f"{lc.name}: operating force", "status": fst, "kind": "estimated",
                           "value": round(fz, 2), "limit": {"min_n": lc.min_force_n, "max_n": lc.max_force_n},
                           "detail": "Force to deflect the flexure. On the snapbox test print, 0.9 N felt like nothing, so a click "
                                     "needs roughly 5-15 N."})
        if conv:
            cst = "pass" if conv["delta_peak_pct"] <= 10 else "warn"
            checks.append({"id": f"conv:{lc.name}", "name": f"{lc.name}: mesh convergence", "status": cst, "kind": "verified",
                           "value": conv["delta_peak_pct"], "limit": 10,
                           "detail": f"Peak {conv['metric']} changed {conv['delta_peak_pct']}% when the mesh was refined "
                                     f"to {conv['fine_size_mm']} mm ({conv['fine_elements']} elements)."})
        statuses += [c["status"] for c in checks]
        cases.append({"name": lc.name, "part": lc.part, "material": meta["material"], "use": lc.use,
                      "nonlinear": lc.nonlinear, "force": lc.force, "displacement": lc.displacement,
                      "orientation": {"euler": euler, "source": why}, "notes": lc.notes,
                      "npz": str((wd / f"{lc.name}.npz").relative_to(proj.dir)),
                      **r, "eval": ev, "convergence": conv, "checks": checks})
    r = {"status": worst([{"status": s} for s in statuses]), "cases": cases,
         "assumptions": ["Isotropic linear-elastic material (xy modulus); strengths are anisotropic (xy vs z).",
                         "Part treated as 100% solid: infill is not modelled.",
                         "No plasticity, creep, fatigue or temperature effects.",
                         "Peaks inside fixed regions and within 1 mm (or 2 elements) of loaded nodes are excluded: those are boundary-condition artifacts.",
                         f"Material data confidence: {', '.join(sorted({config.material(c['material'])['confidence'] for c in cases})) or 'n/a'}."]}
    proj.save("sim", r)
    return r


# ---------------------------------------------------------------- slice
def slice_(proj: Project) -> dict:
    _current(proj)
    m = proj.manifest()
    chk = proj.result("check")
    if not chk or proj.stale("check"):
        raise config.ForgeError("Run `forge check` first (slice uses the checked print orientation).")
    parts, groups = {}, {}
    for name, meta in m["parts"].items():
        if meta.get("purchased"):
            continue
        pr = _printer(proj, name)
        sup_needed = next(c for c in chk["parts"][name]["checks"] if c["id"] == "supports")["value"] > 0.5
        support = {"on": True, "off": False}.get(meta["supports"], sup_needed)
        stl = proj.dir / chk["parts"][name]["print_stl"]
        raw = slicer.slice_files([stl], pr, proj.build_dir / "slice" / name, support, name)
        checks, stats = slicer.assess(raw, pr, support)
        parts[name] = {"status": worst(checks), "checks": checks, "stats": stats}
        groups.setdefault((meta["material"], support), []).append(stl)
    plates = []
    for i, ((mat, support), stls) in enumerate(groups.items(), start=1):
        pr = printer_mod.load(proj.spec.get("printer"), mat)
        nm = f"{proj.name}_plate{i}"
        raw = slicer.slice_files(stls, pr, proj.build_dir / "slice" / f"_plate{i}", support, nm)
        checks, stats = slicer.assess(raw, pr, support)
        plates.append({"name": nm, "material": mat, "support": support, "parts": [s.stem for s in stls],
                       "status": worst(checks), "checks": checks, "stats": stats,
                       "threemf": str(raw["threemf"].relative_to(proj.dir)) if raw["threemf"] else None})
    allc = [c for p in parts.values() for c in p["checks"]] + [c for p in plates for c in p["checks"]]
    r = {"status": worst(allc), "parts": parts, "plates": plates,
         "totals": {"time_s": sum(p["stats"].get("time_s", 0) for p in plates),
                    "filament_g": round(sum(p["stats"].get("filament_g", 0) for p in plates), 2),
                    "support_g": round(sum(p["stats"].get("support_g", 0) for p in plates), 2),
                    "cost": round(sum(p["stats"].get("cost", 0) for p in plates), 2)}}
    proj.save("slice", r)
    try:
        from . import plate
        plate.extract(proj)  # plate meshes as the slicer arranged them (studio plate view)
    except Exception as e:
        proj.journal(f"plate extraction for studio failed: {e}", author="forge", kind="warn")
    return r


# ---------------------------------------------------------------- all
def run_all(proj: Project, converge=True, renders=True, log=print) -> dict:
    log("build")
    build(proj)
    log("orient")
    orient(proj)
    log("check")
    check(proj)
    log("fit")
    fit(proj)
    if proj.manifest()["design"]["loads"]:
        log("sim")
        sim(proj, converge=converge)
        before = {k: v["best"]["euler"] for k, v in proj.result("orient")["parts"].items()}
        log("orient (strength-aware)")
        orient(proj)
        after = {k: v["best"]["euler"] for k, v in proj.result("orient")["parts"].items()}
        if before != after:
            log("orientation changed → re-check + re-sim")
            check(proj)
            sim(proj, converge=converge)
    if proj.manifest()["design"].get("motion"):
        try:
            from . import physics
            log("physics (MuJoCo speed scan)")
            physics.run(proj, rpm=physics.HAND_RPM, do_scan=True)
        except Exception as e:  # physics is advisory; a failure here must not hide the rest
            proj.journal(f"physics stage skipped: {e}", author="forge", kind="warn")
    log("slice")
    slice_(proj)
    if renders:
        from . import render
        log("render")
        render.render_all(proj)
    from . import report
    log("report")
    report.write(proj)
    return status(proj)


def status(proj: Project) -> dict:
    out = {}
    for st in ["build", "orient", "check", "fit", "sim", "physics", "slice", "render", "report"]:
        r = proj.result(st)
        out[st] = {"status": (r or {}).get("status", "—"), "stale": proj.stale(st), "at": (r or {}).get("at")}
    return out
