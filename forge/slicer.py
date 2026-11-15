"""Slice with the real Bambu Studio engine (headless) and read the result back.

The slicer is the ground truth for printability: if Bambu Studio slices it with
these exact presets, it prints. This module also guards against the CLI silently
ignoring presets by checking the G-code header against what was requested."""
from __future__ import annotations

import json
import math
import re
import subprocess
import zipfile
from pathlib import Path

from . import config
from .checks import check
from .printer import Printer


def _header(gcode: str) -> dict:
    out = {}
    for ln in gcode.splitlines()[:6000]:
        m = re.match(r"^; ([a-z_0-9]+) = (.*)$", ln)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"')
        m = re.match(r"^; total filament weight \[g\] : ([\d.]+)", ln)
        if m:
            out["_weight_g"] = float(m.group(1))
        m = re.match(r"^; model printing time: (.*?); total estimated time: (.*)$", ln)
        if m:
            out["_time_str"] = m.group(2).strip()
    return out


def feature_extrusion(gcode: str) -> dict[str, float]:
    """mm of filament per feature type (Bambu uses relative E and '; FEATURE:' tags)."""
    feat, acc, relative = "Other", {}, True
    for ln in gcode.splitlines():
        if ln.startswith("; FEATURE:"):
            feat = ln.split(":", 1)[1].strip()
        elif ln.startswith("M83"):
            relative = True
        elif ln.startswith("M82"):
            relative = False
        elif relative and (ln.startswith("G1 ") or ln.startswith("G2 ") or ln.startswith("G3 ")) and " E" in ln:
            m = re.search(r" E(-?[\d.]+)", ln)
            if m:
                e = float(m.group(1))
                if e > 0:
                    acc[feat] = acc.get(feat, 0.0) + e
    return acc


def slice_files(stls: list[Path], printer: Printer, workdir: Path, support: bool, name: str) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / "out"
    out.mkdir(exist_ok=True)
    for old in out.glob("*"):
        old.unlink()
    m, p, f = printer.write(workdir / "presets", support=support)
    cmd = [str(config.bambu_path()), "--debug", "2", "--load-settings", f"{m};{p}", "--load-filaments", str(f),
           "--slice", "0", "--arrange", "1", "--orient", "0", "--outputdir", str(out),
           "--export-3mf", f"{name}.3mf", *map(str, stls)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd=workdir)
    log = proc.stdout + proc.stderr
    (workdir / "slicer.log").write_text(" ".join(cmd) + "\n\n" + log)
    res_p = out / "result.json"
    res = json.loads(res_p.read_text()) if res_p.exists() else {}
    gcode_p = out / "plate_1.gcode"
    gcode = gcode_p.read_text() if gcode_p.exists() else ""
    tmf = out / f"{name}.3mf"
    if not gcode and tmf.exists():
        with zipfile.ZipFile(tmf) as z:
            gname = next((n for n in z.namelist() if n.endswith(".gcode")), None)
            gcode = z.read(gname).decode() if gname else ""
    errors = [l.split("]")[-1].strip() for l in log.splitlines() if "[error]" in l and "WARNING" not in l]
    warnings = [l.split("]")[-1].strip() for l in log.splitlines() if "[warning]" in l][:20]
    return {"cmd": cmd, "returncode": proc.returncode, "result": res, "gcode": gcode, "header": _header(gcode) if gcode else {},
            "errors": errors, "warnings": warnings, "threemf": tmf if tmf.exists() else None}


def assess(raw: dict, printer: Printer, support: bool) -> tuple[list[dict], dict]:
    checks = []
    res, hdr = raw["result"], raw["header"]
    ok = bool(raw["gcode"]) and res.get("return_code") == 0 and raw["threemf"] is not None
    checks.append(check("slices", "Slices cleanly", "pass" if ok else "fail", "verified",
                        value=res.get("return_code"), detail=res.get("error_string") or "; ".join(raw["errors"][:3]) or "Bambu Studio CLI"))
    if not raw["gcode"]:
        return checks, {}
    # did the slicer actually use our presets?
    want = {"printer_settings_id": printer.machine["name"], "filament_settings_id": printer.filament["name"],
            "curr_bed_type": printer.bed_type, "filament_type": printer.filament["filament_type"][0],
            "print_settings_id": printer.process["name"], **{k: str(v) for k, v in printer.overrides.items()}}
    got = {k: hdr.get(k) for k in want}
    mismatch = {k: (want[k], got[k]) for k in want if str(got[k]) != str(want[k])}
    area = hdr.get("printable_area", "")
    if f"{printer.bed_xy[0]:g}x{printer.bed_xy[1]:g}" not in area.replace(".0", ""):
        mismatch["printable_area"] = (printer.bed_xy, area)
    checks.append(check("presets_applied", "Slicer used the requested presets", "pass" if not mismatch else "fail",
                        "verified", value=got, detail=f"Mismatches: {mismatch}" if mismatch else "G-code header matches."))
    feats = feature_extrusion(raw["gcode"])
    fil_d = 1.75
    g_per_mm = math.pi * (fil_d / 2) ** 2 * printer.density / 1000
    grams = {k: round(v * g_per_mm, 2) for k, v in feats.items()}
    total_g = round(sum(grams.values()), 2)
    sup_g = round(sum(v for k, v in grams.items() if "upport" in k), 2)
    plates = res.get("sliced_plates") or [{}]
    t = plates[0].get("total_predication") or 0
    stats = {
        "time_s": round(float(t), 1), "time_str": hdr.get("_time_str", ""),
        "filament_g": total_g, "support_g": sup_g,
        "support_pct": round(100 * sup_g / total_g, 1) if total_g else 0.0,
        "cost": round(total_g / 1000 * printer.cost_per_kg, 2),
        "layers": int(hdr.get("total_layer_number", 0) or 0) or None,
        "feature_g": grams, "feature_time_s": {k: round(v, 1) for k, v in (plates[0].get("feature_type_times") or {}).items()},
        "support_enabled": support, "settings": printer.summary(),
        "slicer_warnings": raw["warnings"],
    }
    if support:
        checks.append(check("support_waste", "Support material", "pass" if stats["support_pct"] < 10 else "warn", "verified",
                            value=stats["support_pct"], limit=10, detail="% of filament that goes into supports (from the G-code)."))
    return checks, stats
