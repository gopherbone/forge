"""Feature-level FDM footguns, found on the exact B-rep (STEP) rather than the mesh.

Cylindrical faces spanning ≥ 180° are recognised as holes (concave) or bosses/pins
(convex). Their axes are rotated into the print frame, then:
  - horizontal holes: the crown droops, so the hole prints oval and undersized (shafts bind)
  - small vertical holes: shrink 0.1-0.2 mm, so pins won't go in
  - slender pins/shafts standing upright: layer lines run across the axis, so they snap at a layer
And from the print-frame mesh's layer sections:
  - holes in the first layer: elephant foot squeezes them (relieve, don't chamfer: chamfers at the plate curl)
  - slender towers: a small cross-section persisting up the part wobbles and snaps
  - many far-apart islands per layer: PETG strings between them"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from . import check


def cylinders(step: Path) -> list[dict]:
    from build123d import GeomType, import_step
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    shape = import_step(step)
    out = []
    for f in shape.faces():
        if f.geom_type != GeomType.CYLINDER:
            continue
        ad = BRepAdaptor_Surface(f.wrapped)
        cyl = ad.Cylinder()
        umin, umax, vmin, vmax = BRepTools.UVBounds_s(f.wrapped)
        span = umax - umin
        if span < math.pi - 1e-3:  # fillets and partial arcs are not holes/pins
            continue
        ax = cyl.Axis()
        d = np.array([ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()])
        o = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()])
        c = f.center()
        p = np.array([c.X, c.Y, c.Z])
        n = f.normal_at(c)
        radial = (p - o) - np.dot(p - o, d) * d
        concave = float(np.dot(np.array([n.X, n.Y, n.Z]), radial)) < 0
        out.append({"r": cyl.Radius(), "axis": d, "length": float(vmax - vmin), "hole": concave,
                    "full": span > 2 * math.pi - 1e-3, "center": p})
    return out


def analyze(step: Path, R: np.ndarray, mesh, printer, rules: dict, fit_parts: bool) -> list[dict]:
    checks = []
    cyl = cylinders(step)
    horiz_holes, small_vholes, upright_pins = [], [], []
    for c in cyl:
        a = R @ c["axis"]
        vertical = abs(a[2]) > 0.9
        horizontal = abs(a[2]) < 0.3
        dia = 2 * c["r"]
        if c["hole"] and horizontal and dia >= 3.0:
            horiz_holes.append(round(dia, 2))
        if c["hole"] and vertical and dia < 3.0:
            small_vholes.append(round(dia, 2))
        if not c["hole"] and vertical and dia <= 6.0 and c["length"] > 2.5 * dia:
            upright_pins.append(f"Ø{dia:.1f}×{c['length']:.1f}")
    hh = sorted(set(horiz_holes))
    checks.append(check("horizontal_holes", "Round holes lying horizontal", "warn" if hh and fit_parts else ("info" if hh else "pass"),
                        "heuristic", value=hh,
                        detail="Diameters (mm) of round holes whose axis lies flat. The top of the hole is an overhang that droops, "
                               "so it prints a little oval and undersized. For shafts and pins, use a teardrop or flat-top hole, "
                               "add ~0.1 mm, or orient the axis vertically." + (" This part has declared fits." if fit_parts else "")))
    checks.append(check("small_vertical_holes", "Small vertical holes", "warn" if small_vholes else "pass", "heuristic",
                        value=sorted(set(small_vholes)),
                        detail="Vertical holes under 3 mm shrink ~0.1-0.2 mm (the slicer's polygon approximation and squish). "
                               "Oversize them or ream them."))
    checks.append(check("upright_pins", "Pins/shafts printed upright", "warn" if upright_pins else "pass", "heuristic",
                        value=upright_pins[:8],
                        detail="Slender cylinders standing vertically have layer lines across their axis and snap at a layer "
                               "when bent. Lay pins and shafts flat (give them a flat to sit on), or make them thicker."))

    # --- layer-section based ---
    zmin, zmax = mesh.bounds[0][2], mesh.bounds[1][2]
    layer = printer.layer
    hs = np.linspace(zmin + layer * 0.5, zmax - layer * 0.5, int(min(150, max(3, (zmax - zmin) / layer))))
    secs = mesh.section_multiplane(plane_origin=[0, 0, 0], plane_normal=[0, 0, 1], heights=list(hs))
    # holes in the first layer
    first = secs[0]
    holes0 = []
    if first is not None:
        for poly in first.polygons_full:
            for ring in poly.interiors:
                from shapely.geometry import Polygon
                h = Polygon(ring)
                deq = 2 * math.sqrt(h.area / math.pi)
                if 0.5 < deq <= 15.0:  # functional holes; big openings (open-bottom boxes) aren't fits
                    holes0.append(round(deq, 2))
    checks.append(check("first_layer_holes", "Holes at the plate", "warn" if holes0 else "pass", "verified",
                        value=sorted(holes0)[:10],
                        detail="Equivalent diameters (mm) of holes cut through the first layer. Elephant foot squeezes them. Do NOT chamfer "
                               "the entry (chamfers at the plate curled on the test print): add a +0.3 mm stepped relief for the first "
                               "2-3 layers, or set the slicer's hole compensation, or move the hole off the plate."))
    # sharp vertical corners on big footprints lift (warp): fillet edges normal to the bed
    sharp = []
    if first is not None:
        from shapely.geometry import Polygon as _P
        for poly in first.polygons_full:
            if max(poly.bounds[2] - poly.bounds[0], poly.bounds[3] - poly.bounds[1]) < rules.get("warp_footprint_mm", 40):
                continue
            ring = np.asarray(poly.simplify(0.05).exterior.coords)[:-1]
            n = len(ring)
            for i in range(n):
                a, b, c = ring[i - 1], ring[i], ring[(i + 1) % n]
                u, v = a - b, c - b
                if np.linalg.norm(u) < 1.5 or np.linalg.norm(v) < 1.5:
                    continue  # short segments belong to an arc (a filleted corner)
                ang = np.degrees(np.arccos(np.clip(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v)), -1, 1)))
                cross = u[0] * v[1] - u[1] * v[0]
                if ang < 135 and cross < 0:  # convex corner (CCW exterior), sharper than 135°
                    sharp.append(round(float(ang)))
    checks.append(check("sharp_corners", "Vertical corners on the plate", "warn" if sharp else "pass", "heuristic",
                        value=sharp[:10],
                        detail="Corner angles (°) of sharp convex corners in the first layer of footprints ≥ 40 mm. Sharp corners "
                               "concentrate shrinkage and lift. Fillet vertical edges (r ≥ 2-3 mm); Markforged recommends filleting "
                               "edges normal to the bed to reduce warping."))
    # slender towers: small cross-sections persisting over height
    small_a = rules.get("slender_area_mm2", 10.0)
    run = best = 0.0
    dz = hs[1] - hs[0] if len(hs) > 1 else layer
    spread = 0
    from shapely.geometry import MultiPolygon
    for s in secs:
        if s is None:
            run = 0.0
            continue
        polys = list(s.polygons_full)
        if any(p.area < small_a for p in polys) and len(polys) >= 1:
            run += dz
            best = max(best, run)
        else:
            run = 0.0
        if len(polys) >= 4:
            cents = np.array([[p.centroid.x, p.centroid.y] for p in polys])
            far = np.linalg.norm(cents[:, None] - cents[None], axis=-1).max()
            if far > 15:
                spread += 1
    tall = best >= rules.get("slender_height_mm", 6.0)
    checks.append(check("slender_towers", "No slender towers", "warn" if tall else "pass", "measured",
                        value=round(best, 1), limit=rules.get("slender_height_mm", 6.0),
                        detail=f"Longest run (mm of height) of a cross-section under {small_a:g} mm² (~Ø3.5 mm). Thin towers "
                               "wobble, ring and snap. Thicken them, add a fillet or gusset at the root, or print them lying down."))
    frac = spread / max(len(secs), 1)
    checks.append(check("stringing", "PETG stringing risk", "info" if frac > 0.3 else "pass", "heuristic",
                        value=round(frac, 2),
                        detail="Fraction of layers with 4+ islands spread over 15 mm. Each layer then travels between islands, "
                               "and PETG strings. Dry the filament, and consider printing parts separately or merging islands."))
    return checks
