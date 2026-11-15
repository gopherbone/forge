"""Printability analysis of one part in its print orientation."""
from __future__ import annotations

import numpy as np
import trimesh
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .. import config
from ..geometry import DIRS, rot
from ..printer import Printer
from . import check, worst

# face classes (stored per face for heatmap renders)
OK, BED, COSMETIC_OVERHANG, BRIDGE, SHORT_OVERHANG, SUPPORT = 0, 1, 2, 3, 4, 5
CLASS_NAMES = {OK: "ok", BED: "on bed", COSMETIC_OVERHANG: "steep overhang", BRIDGE: "bridge",
               SHORT_OVERHANG: "short overhang", SUPPORT: "needs support"}


def _components(mesh: trimesh.Trimesh, mask: np.ndarray) -> list[np.ndarray]:
    idx = np.nonzero(mask)[0]
    if len(idx) == 0:
        return []
    adj = mesh.face_adjacency
    keep = mask[adj[:, 0]] & mask[adj[:, 1]]
    return [np.asarray(c) for c in trimesh.graph.connected_components(adj[keep], nodes=idx, min_len=1)]


def _short_span(mesh: trimesh.Trimesh, faces: np.ndarray) -> tuple[float, float]:
    polys = [Polygon(mesh.vertices[f][:, :2]) for f in mesh.faces[faces]]
    polys = [p.buffer(1e-4) for p in polys if p.area > 1e-9]
    if not polys:
        return 0.0, 0.0
    u = unary_union(polys)
    r = u.minimum_rotated_rectangle
    xs, ys = r.exterior.coords.xy
    e = [np.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(2)]
    return float(min(e)), float(u.area)


def classify_faces(mesh: trimesh.Trimesh, printer: Printer, rules: dict) -> tuple[np.ndarray, list[dict]]:
    n = mesh.face_normals
    down = -n[:, 2]
    zmin = mesh.bounds[0][2]
    fz = mesh.vertices[mesh.faces][:, :, 2]
    cls = np.full(len(mesh.faces), OK, dtype=np.int8)
    on_bed = (fz.max(axis=1) < zmin + printer.layer * 0.5) & (down > 0.99)
    cls[on_bed] = BED
    sup = (down > np.cos(np.radians(printer.support_angle))) & ~on_bed
    cos_ = (down > np.cos(np.radians(rules["cosmetic_overhang_deg"]))) & ~sup & ~on_bed
    cls[cos_] = COSMETIC_OVERHANG
    regions = []
    for comp in _components(mesh, sup):
        span, area = _short_span(mesh, comp)
        flat = bool(np.all(down[comp] > 0.98))
        anchors, reach = None, None
        if flat:
            c, anchors, reach = _flat_region(mesh, comp, printer, rules)
            span = 2 * reach if (anchors or 0) >= 2 else reach
        elif span <= 5.0:
            c = SHORT_OVERHANG
        else:
            c = SUPPORT
        cls[comp] = c
        regions.append({"class": CLASS_NAMES[c], "area_mm2": round(area, 2), "short_span_mm": round(span, 2),
                        "z_mm": round(float(fz[comp].min()), 2), "flat": flat, "anchors": anchors})
    return cls, regions


def _flat_region(mesh, comp, printer, rules):
    """Classify a flat downward region the way a slicer sees it. Anchors are the parts of
    its outline that rest on material in the layer just below. A bridge needs two or more
    separate anchors and a short distance between them. A ledge with one anchor is fine
    only if it sticks out a little."""
    import shapely
    polys = [Polygon(mesh.vertices[f][:, :2]) for f in mesh.faces[comp]]
    P = unary_union([p.buffer(1e-4) for p in polys if p.area > 1e-9]).buffer(0)
    z0 = float(mesh.vertices[mesh.faces[comp]][:, :, 2].mean())
    # horizontal plane through the world origin: section coordinates are world XY
    sec = mesh.section_multiplane(plane_origin=[0, 0, 0], plane_normal=[0, 0, 1], heights=[z0 - printer.layer * 0.5])[0]
    below = unary_union(list(sec.polygons_full)) if sec is not None else None
    if below is None or below.is_empty:
        return SUPPORT, 0, float("inf")
    anchor = P.boundary.intersection(below.buffer(0.15))
    if anchor.is_empty:
        return SUPPORT, 0, float("inf")
    blob = anchor.buffer(0.3)
    n = len(getattr(blob, "geoms", [blob]))  # separate anchored stretches of the outline
    minx, miny, maxx, maxy = P.bounds
    step = max(0.25, max(maxx - minx, maxy - miny) / 60)
    gx, gy = np.meshgrid(np.arange(minx, maxx + step, step), np.arange(miny, maxy + step, step))
    pts = shapely.points(gx.ravel(), gy.ravel())
    pts = pts[shapely.contains(P, pts)]
    if len(pts) == 0:
        pts = shapely.points(np.asarray(P.exterior.coords))
    reach = float(shapely.distance(pts, anchor).max())
    if n >= 2 and 2 * reach <= rules["bridge_max_mm"]:
        return BRIDGE, n, reach
    if reach <= 3.0:
        return SHORT_OVERHANG, n, reach
    return SUPPORT, n, reach


def analyze(mesh: trimesh.Trimesh, printer: Printer, part_meta: dict, euler) -> tuple[list[dict], dict]:
    rules = config.rules()
    checks: list[dict] = []
    extra: dict = {}

    # --- manifold / solidity (verified) ---
    bodies = len(mesh.split(only_watertight=False))
    ok = mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0
    checks.append(check("manifold", "Watertight solid", "pass" if ok else "fail", "verified",
                        value={"watertight": bool(mesh.is_watertight), "winding": bool(mesh.is_winding_consistent),
                               "volume_mm3": round(float(mesh.volume), 2)},
                        detail="Mesh must be a closed, consistently wound solid."))
    want = part_meta.get("bodies", 1)
    checks.append(check("bodies", "Body count", "pass" if bodies == want else "warn", "verified", value=bodies,
                        limit=want, detail="Unexpected disconnected bodies usually mean a bad boolean."))

    # --- bed fit (verified, limits from machine preset) ---
    w, d, h = mesh.extents
    bx, by = printer.bed_xy
    ex, ey = printer.exclude_xy
    fits = h <= printer.bed_z and ((w <= bx and d <= by - ey) or (w <= bx - ex and d <= by) or (d <= bx and w <= by - ey))
    checks.append(check("bed_fit", "Fits build volume", "pass" if fits else "fail", "verified",
                        value=[round(w, 1), round(d, 1), round(h, 1)], limit=[bx, by, printer.bed_z],
                        detail=f"{printer.machine['name']}; exclude zone {ex:.0f}x{ey:.0f} mm in a corner."))

    # --- overhangs / bridges / supports ---
    cls, regions = classify_faces(mesh, printer, rules)
    area = mesh.area_faces
    sup_area = float(area[cls == SUPPORT].sum())
    supports_mode = part_meta.get("supports", "auto")
    if sup_area < 0.5:
        st, det = "pass", "No region needs support."
    elif supports_mode == "on":
        st, det = "warn", "Supports explicitly allowed for this part (supports='on'). Keep them minimal and off show faces."
    else:
        st, det = "fail", ("Needs supports. The user's rule is zero supports (minimal at most): redesign the overhang, "
                           "re-orient, split the part, or opt in with Part(supports='on') and log why.")
    checks.append(check("supports", "Support-free", st, "verified", value=round(sup_area, 1), limit=0,
                        detail=f"{det} Threshold: slopes under {printer.support_angle:.0f}° from horizontal "
                               f"(from the process preset)."))
    br = [r for r in regions if r["class"] == "bridge"]
    checks.append(check("bridges", "Bridges within span limit", "pass" if br else "info", "heuristic",
                        value=[r["short_span_mm"] for r in br], limit=rules["bridge_max_mm"],
                        detail=f"{len(br)} flat unsupported span(s) at or under {rules['bridge_max_mm']} mm, treated as bridges."))
    cos_area = float(area[cls == COSMETIC_OVERHANG].sum())
    checks.append(check("steep_overhang", "Overhang surface quality", "pass" if cos_area < 1 else "info", "heuristic",
                        value=round(cos_area, 1),
                        detail=f"mm² of slopes between {printer.support_angle:.0f}° and {rules['cosmetic_overhang_deg']}°: "
                               f"they print without support but look rougher."))

    # --- rounded edges coming off the plate (verified geometry, user rule) ---
    zmin0 = mesh.bounds[0][2]
    fzmin = mesh.vertices[mesh.faces][:, :, 2].min(axis=1)
    down = -mesh.face_normals[:, 2]
    near = (fzmin < zmin0 + rules["bed_edge_zone_mm"]) & (cls != BED)
    shallow = down > np.cos(np.radians(rules["bed_edge_max_slope_deg"]))  # slope from horizontal < limit
    edge_faces = near & shallow
    # only the part's OUTER edge curls; ledges inside holes (e.g. a stepped elephant-foot relief) don't count
    try:
        from shapely.geometry import Point
        sec0 = mesh.section_multiplane(plane_origin=[0, 0, 0], plane_normal=[0, 0, 1], heights=[zmin0 + printer.layer * 0.5])[0]
        if sec0 is not None and edge_faces.any():
            outer = unary_union([Polygon(p.exterior) for p in sec0.polygons_full]).boundary
            cent = mesh.triangles_center[edge_faces][:, :2]
            keep = np.array([outer.distance(Point(c)) < 2.5 for c in cent])
            idx = np.nonzero(edge_faces)[0]
            edge_faces[idx[~keep]] = False
    except Exception:
        pass
    edge_area = float(mesh.area_faces[edge_faces].sum())
    checks.append(check("bed_edge", "No rounded edges at the plate", "warn" if edge_area > 0.5 else "pass", "verified",
                        value=round(edge_area, 1), limit=0,
                        detail=f"mm² of downward surface flatter than {rules['bed_edge_max_slope_deg']:.0f}° from horizontal "
                               f"within {rules['bed_edge_zone_mm']} mm of the plate (fillets, domes, undercut spheres). "
                               "Walls must meet the plate vertically: rounds and chamfers at the plate curled on the snapbox test print (PETG, textured PEI). Leave elephant foot to the slicer's compensation."))
    extra["bed_edge_faces"] = edge_faces

    # --- thin horizontal voids that fuse (snap fingers under bridges, clearance slots in Z) ---
    nzf = mesh.face_normals[:, 2]
    zf_min = mesh.vertices[mesh.faces][:, :, 2].min(axis=1)
    ceil = np.nonzero((nzf < -0.9) & (zf_min > mesh.bounds[0][2] + printer.layer * 0.5))[0]
    fuse = []
    if len(ceil):
        origins = mesh.triangles_center[ceil] - np.array([0, 0, 1e-3])
        dirs = np.tile([0.0, 0.0, -1.0], (len(ceil), 1))
        try:
            locs, idx_ray, idx_tri = mesh.ray.intersects_location(origins, dirs, multiple_hits=False)
            for loc, r, tri in zip(locs, idx_ray, idx_tri):
                gap = origins[r][2] - loc[2]
                if 0.02 < gap < rules.get("fuse_gap_layers", 3) * printer.layer and mesh.face_normals[tri][2] > 0.9:
                    fuse.append(round(float(gap), 2))
        except Exception:
            pass
    checks.append(check("z_fuse", "No thin horizontal gaps", "warn" if fuse else "pass", "measured",
                        value=sorted(set(fuse))[:8], limit=round(rules.get("fuse_gap_layers", 3) * printer.layer, 2),
                        detail=f"Vertical gaps (mm) under overhanging faces thinner than {rules.get('fuse_gap_layers', 3)} layers. "
                               "A bridge or ceiling over such a gap sags and welds the parts below it together: a fused snap "
                               "finger or clearance. Make Z gaps ≥ 3 layers (0.6 mm) and land them on layer boundaries."))

    # --- rounded surfaces facing up: layer lines stair-step on shallow curves (user rule) ---
    nz = mesh.face_normals[:, 2]
    band = (nz > np.cos(np.radians(75))) & (nz < np.cos(np.radians(8)))  # sloped 8-75 degrees, facing up
    curved = np.zeros(len(mesh.faces), dtype=bool)
    adj, ang = mesh.face_adjacency, mesh.face_adjacency_angles
    smooth = (ang > np.radians(0.5)) & (ang < np.radians(25))  # tessellated curvature, not a crisp edge
    curved[adj[smooth, 0]] = True
    curved[adj[smooth, 1]] = True
    up_curved = band & curved
    uc_area = float(mesh.area_faces[up_curved].sum())
    top_area = float(mesh.area_faces[nz > 0.1].sum())
    frac = uc_area / max(top_area, 1e-9)
    st = "warn" if (uc_area > rules.get("up_curve_warn_mm2", 80) and frac > rules.get("up_curve_warn_frac", 0.08)) else "pass"
    checks.append(check("up_curves", "No rounded surfaces facing up", st, "heuristic",
                        value={"area_mm2": round(uc_area, 1), "fraction_of_top": round(frac, 3)},
                        limit={"mm2": rules.get("up_curve_warn_mm2", 80), "fraction": rules.get("up_curve_warn_frac", 0.08)},
                        detail="Curved surfaces sloping 8-75° upward (domes, big top rounds) stair-step: every layer shows as a "
                               "contour ring. User rule: simple and minimal. Prefer flat tops, vertical walls, crisp small edge breaks."))
    extra["up_curve_faces"] = up_curved

    # --- cosmetic faces ---
    R = rot(euler)
    notes = []
    status = "pass"
    for c in part_meta.get("cosmetic", []):
        v = R @ np.asarray(DIRS[c], float)
        faces = mesh.face_normals @ v > 0.9
        if not faces.any():
            notes.append(f"{c}: no faces")
            continue
        if (cls[faces] == SUPPORT).any():
            status = "warn"
            notes.append(f"{c}: support touches this show face")
        elif (cls[faces] == BED).any():
            notes.append(f"{c}: on the bed, gets the plate's texture ({printer.bed_type})")
        elif v[2] > 0.9:
            notes.append(f"{c}: faces up, so the top-surface finish is the best")
        elif abs(v[2]) < 0.3:
            notes.append(f"{c}: vertical wall, layer lines and seam visible")
        else:
            notes.append(f"{c}: sloped {np.degrees(np.arcsin(abs(v[2]))):.0f}°, stair-stepping visible")
    if part_meta.get("cosmetic"):
        checks.append(check("cosmetic", "Show faces", status, "heuristic", value=notes,
                            detail="Where each declared show face ends up in this orientation."))

    # --- wall thickness (measured) ---
    lw = printer.line_width
    pts, fidx = trimesh.sample.sample_surface_even(mesh, rules["thickness_samples"], seed=1)
    th = trimesh.proximity.thickness(mesh, pts, exterior=False, normals=mesh.face_normals[fidx], method="ray")
    th = np.where(np.isfinite(th), th, np.nan)
    fail_t, warn_t = rules["min_wall_fail_lines"] * lw, rules["min_wall_warn_lines"] * lw
    valid = th[np.isfinite(th)]
    frac_fail = float((valid < fail_t).mean()) if len(valid) else 0.0
    frac_warn = float((valid < warn_t).mean()) if len(valid) else 0.0
    p2 = float(np.nanpercentile(th, 2)) if len(valid) else float("nan")
    st = "fail" if frac_fail > 0.01 else "warn" if frac_warn > 0.02 else "pass"
    checks.append(check("wall_thickness", "Wall thickness", st, "measured",
                        value={"p2_mm": round(p2, 2), "pct_under_fail": round(100 * frac_fail, 2),
                               "pct_under_warn": round(100 * frac_warn, 2)},
                        limit={"fail_mm": round(fail_t, 2), "warn_mm": round(warn_t, 2)},
                        detail=f"Ray-cast thickness at {len(pts)} surface samples. Fail: walls under 1 line "
                               f"({fail_t:.2f} mm). Warn: under 2 lines ({warn_t:.2f} mm)."))
    extra["thickness"] = {"points": pts, "t": th}

    # --- first layer + islands (sections) ---
    zmax = mesh.bounds[1][2]
    layer = printer.layer
    heights = np.unique(np.concatenate([[layer * 0.5], np.linspace(layer * 1.5, zmax - layer * 0.5, min(120, max(2, int(zmax / layer))))]))
    secs = mesh.section_multiplane(plane_origin=[0, 0, 0], plane_normal=[0, 0, 1], heights=list(heights))
    first_area = 0.0
    tiny = []
    for z, s in zip(heights, secs):
        if s is None:
            continue
        polys = s.polygons_full
        if z == heights[0]:
            first_area = float(sum(p.area for p in polys))
        for p in polys:
            if p.area < rules["tiny_island_mm2"]:
                tiny.append(round(float(z), 2))
    checks.append(check("bed_contact", "First-layer contact", "pass" if first_area >= rules["min_bed_contact_mm2"] else "warn",
                        "verified", value=round(first_area, 1), limit=rules["min_bed_contact_mm2"],
                        detail="mm² touching the plate. Small contact means a brim or mouse ears."))
    tip = zmax / max(np.sqrt(first_area), 1e-6)
    checks.append(check("tip_ratio", "Stability while printing", "pass" if tip < rules["tip_ratio_warn"] else "warn",
                        "heuristic", value=round(float(tip), 2), limit=rules["tip_ratio_warn"],
                        detail="Height / sqrt(contact area). Tall, narrow prints wobble and get knocked off."))
    checks.append(check("islands", "No tiny islands", "pass" if not tiny else "warn", "measured",
                        value=sorted(set(tiny))[:12], limit=rules["tiny_island_mm2"],
                        detail="Layer heights where a cross-section is smaller than the limit (mm²), at up to 120 sampled heights."))
    extra["face_class"] = cls
    extra["regions"] = regions
    return checks, extra


def summarize(checks):
    return worst(checks)
