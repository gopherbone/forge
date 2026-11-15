"""Renders for human review: hero, exploded, turntable, print-bed heatmaps, FEA.

All renders share one dark 'viewport' look so they read as a set in the report."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyvista as pv

from . import geometry
from .checks.printability import BED, BRIDGE, COSMETIC_OVERHANG, OK, SHORT_OVERHANG, SUPPORT
from .project import Project

pv.OFF_SCREEN = True
BG_TOP, BG_BOT = "#2a3541", "#0d1217"
PALETTE = ["#2ec4b6", "#ff9f1c", "#e0e6ed", "#7b9acc", "#f25f5c", "#9bc53d"]
FACE_COLORS = {OK: "#c9d3dc", BED: "#5b6b7a", COSMETIC_OVERHANG: "#ffd166", BRIDGE: "#4cc9f0",
               SHORT_OVERHANG: "#f4a261", SUPPORT: "#ef476f"}
W, H = 1600, 1000


def _plotter(w=W, h=H, floor_z: float | None = None, shadows: bool = False):
    """Studio look: gradient backdrop, key/fill/rim directional lights, optional floor + shadows."""
    import vtk
    vtk.vtkObject.GlobalWarningDisplayOff()
    p = pv.Plotter(off_screen=True, window_size=(w, h), lighting="none")
    p.set_background(BG_BOT, top=BG_TOP)
    for pos, inten in (((120, -160, 180), 1.0), ((-150, -40, 80), 0.35), ((0, 160, 60), 0.55)):
        p.add_light(pv.Light(position=pos, focal_point=(0, 0, 0), intensity=inten, positional=False))
    if floor_z is not None:
        p.add_mesh(pv.Plane(center=(0, 0, floor_z - 0.05), i_size=5000, j_size=5000), color="#161d24", ambient=0.25)
    if shadows:
        try:
            p.enable_shadows()
        except Exception:
            pass
    try:
        p.enable_anti_aliasing("ssaa")
    except Exception:
        pass
    return p


def _mat(p, mesh, color, **kw):
    return p.add_mesh(mesh, color=color, pbr=True, metallic=0.05, roughness=0.42, smooth_shading=True,
                      split_sharp_edges=True, **kw)


def _bed(p, size=(256, 256), z=-0.05):
    plate = pv.Plane(center=(size[0] / 2, size[1] / 2, z - 0.6), direction=(0, 0, 1), i_size=size[0], j_size=size[1])
    p.add_mesh(plate, color="#1d252d", pbr=True, roughness=0.9, metallic=0.0)
    lines = []
    for x in np.arange(0, size[0] + 1, 16):
        lines.append(pv.Line((x, 0, z), (x, size[1], z)))
    for y in np.arange(0, size[1] + 1, 16):
        lines.append(pv.Line((0, y, z), (size[0], y, z)))
    p.add_mesh(pv.merge(lines), color="#3a4652", line_width=1, opacity=0.6)


def _tm_to_pv(m):
    faces = np.hstack([np.full((len(m.faces), 1), 3), m.faces]).ravel()
    return pv.PolyData(np.asarray(m.vertices), faces)


def _colors(meta_parts):
    out = {}
    for i, (n, v) in enumerate(meta_parts.items()):
        out[n] = v.get("color") or PALETTE[i % len(PALETTE)]
    return out


def _frame(p, meshes, view=(1, -1.35, 0.85), zoom=1.0):
    b = pv.merge(meshes).bounds
    c = np.array([(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2])
    d = np.linalg.norm([b[1] - b[0], b[3] - b[2], b[5] - b[4]])
    v = np.asarray(view, float)
    v /= np.linalg.norm(v)
    p.camera_position = [tuple(c + v * d * 1.9 / zoom), tuple(c), (0, 0, 1)]
    p.camera.view_angle = 28


def hero(proj: Project, out: Path, explode: float = 0.0, turntable: bool = True) -> dict:
    m = proj.manifest()
    cols = _colors(m["parts"])
    meshes = {n: pv.read(proj.dir / v["placed_stl"]) for n, v in m["parts"].items()}
    files = {}
    allc = np.mean([mm.center for mm in meshes.values()], axis=0)

    zmin = min(mm.bounds[4] for mm in meshes.values())

    def scene(exp):
        p = _plotter()
        placed = []
        for n, mm in meshes.items():
            off = np.asarray(m.get("explode", {}).get(n) or (np.asarray(mm.center) - allc) * 0.6) * exp
            mm2 = mm.translate(off, inplace=False)
            _mat(p, mm2, cols[n])
            placed.append(mm2)
        return p, placed

    p, placed = scene(0.0)
    _frame(p, placed)
    files["hero"] = out / "hero.png"
    p.screenshot(files["hero"])
    if turntable:
        import imageio.v2 as imageio
        frames = []
        cam = p.camera
        for _ in range(48):
            cam.Azimuth(7.5)  # incremental; the azimuth property sets an absolute angle
            p.render()
            frames.append(p.screenshot(return_img=True)[::2, ::2])
        files["turntable"] = out / "turntable.gif"
        imageio.mimsave(files["turntable"], frames, duration=0.06, loop=0)
    p.close()
    if len(meshes) > 1:
        p, placed = scene(1.0)
        _frame(p, placed, zoom=0.9)
        files["exploded"] = out / "exploded.png"
        p.screenshot(files["exploded"])
        p.close()
    return {k: str(v.relative_to(proj.dir)) for k, v in files.items()}


def section(proj: Project, out: Path) -> dict:
    """Cutaway through the assembly (plane normal +Y through the assembly centre, or
    spec.yaml render.section_y). Shows how parts engage: lips in windows, gaps, walls."""
    m = proj.manifest()
    cols = _colors(m["parts"])
    meshes = {n: pv.read(proj.dir / v["placed_stl"]) for n, v in m["parts"].items()}
    allb = pv.merge(list(meshes.values())).bounds
    y = (proj.spec.get("render") or {}).get("section_y", (allb[2] + allb[3]) / 2)
    p = _plotter(floor_z=allb[4], shadows=True)
    cut = []
    for n, mm in meshes.items():
        try:
            c = mm.clip_closed_surface(normal=(0, 1, 0), origin=(0, y, 0))
        except Exception:
            c = mm.clip(normal=(0, 1, 0), origin=(0, y, 0))
        if c.n_points:
            _mat(p, c, cols[n])
            cut.append(c)
    if not cut:
        p.close()
        return {}
    _frame(p, cut, view=(0.55, -1.0, 0.45), zoom=1.05)
    f = out / "section.png"
    p.screenshot(f)
    p.close()
    return {"section": str(f.relative_to(proj.dir))}


def motion_gif(proj: Project, out: Path) -> dict:
    """Loop the mechanism through its cycle from the sweep's per-pose STLs."""
    fit = proj.result("fit") or {}
    mo = fit.get("motion") or {}
    frames = mo.get("frames") or []
    if not frames:
        return {}
    import imageio.v2 as imageio
    m = proj.manifest()
    cols = _colors(m["parts"])
    mdir = proj.build_dir / "motion"
    allm = [pv.read(p) for p in mdir.glob(f"{frames[0]}_*.stl")]
    imgs = []
    p = _plotter(1000, 760)
    actors = []
    for k, tag in enumerate(frames):
        for a in actors:
            p.remove_actor(a)
        actors = []
        meshes = []
        for n in m["parts"]:
            f = mdir / f"{tag}_{n}.stl"
            if f.exists():
                mm = pv.read(f)
                meshes.append(mm)
                actors.append(_mat(p, mm, cols[n]))
        if k == 0:
            _frame(p, meshes + allm, view=(1, -1.25, 0.6), zoom=1.05)
        p.add_text(f"{mo['param']} = {int(tag)}°", position="lower_left", font_size=11, color="#9fb0c0", name="angle")
        p.render()
        imgs.append(p.screenshot(return_img=True))
    p.close()
    f = out / "motion.gif"
    imageio.mimsave(f, imgs, duration=0.09, loop=0)
    return {"motion": str(f.relative_to(proj.dir))}


def print_views(proj: Project, out: Path) -> dict:
    chk = proj.result("check")
    files = {}
    for name, c in chk["parts"].items():
        if c.get("purchased") or "print_stl" not in c:
            continue  # bought hardware isn't printed
        import trimesh
        tm = trimesh.load_mesh(proj.dir / c["print_stl"], process=False)
        z = np.load(proj.dir / c["npz"])
        bed = tuple(c["printer"]["bed_mm"][:2])
        poly = _tm_to_pv(tm)
        cls = z["face_class"]
        if len(cls) != poly.n_cells:  # mesh was re-processed differently; skip colouring
            cls = np.zeros(poly.n_cells, dtype=int)
        rgb = np.array([[int(FACE_COLORS[int(k)][i:i + 2], 16) for i in (1, 3, 5)] for k in cls], dtype=np.uint8)
        poly.cell_data["rgb"] = rgb
        # overhang map (seen from below-front so downward faces show)
        p = _plotter(1200, 900)
        _bed(p, bed)
        p.add_mesh(poly, scalars="rgb", rgb=True, pbr=True, roughness=0.5, metallic=0.0)
        _frame(p, [poly], view=(0.9, -1.4, 0.35), zoom=1.15)
        f = out / f"{name}_overhang.png"
        p.screenshot(f)
        p.close()
        files[f"{name}_overhang"] = str(f.relative_to(proj.dir))
        # thickness map
        pts, th = z["th_points"], z["th"]
        ok = np.isfinite(th)
        cloud = pv.PolyData(pts[ok])
        cloud["wall mm"] = np.clip(th[ok], 0, 4)
        p = _plotter(1200, 900)
        _bed(p, bed)
        p.add_mesh(poly, color="#56626e", opacity=0.25)
        p.add_mesh(cloud, scalars="wall mm", cmap="turbo_r", clim=(0, 4), render_points_as_spheres=True, point_size=7,
                   scalar_bar_args={"title": "wall thickness (mm)", "color": "#dfe6ec", "vertical": True,
                                    "position_x": 0.86, "position_y": 0.2, "height": 0.6, "width": 0.05})
        _frame(p, [poly], view=(1, -1.2, 0.9), zoom=1.15)
        f = out / f"{name}_thickness.png"
        p.screenshot(f)
        p.close()
        files[f"{name}_thickness"] = str(f.relative_to(proj.dir))
    return files


def fea_views(proj: Project, out: Path) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .sim.fea import von_mises
    r = proj.result("sim")
    files = {}
    if not r:
        return files
    for case in r["cases"]:
        z = np.load(proj.dir / case["npz"])
        grid = pv.UnstructuredGrid({pv.CellType.QUADRATIC_TETRA: z["tets"]}, z["nodes"])
        grid.point_data["U"] = z["U"]
        if case["use"] == "static":
            grid.point_data["v"] = von_mises(z["S"])
            title, clim = "von Mises (MPa)", None
        else:
            E = z["E"]
            T = np.zeros((len(E), 3, 3))
            T[:, 0, 0], T[:, 1, 1], T[:, 2, 2] = E[:, 0], E[:, 1], E[:, 2]
            T[:, 0, 1] = T[:, 1, 0] = E[:, 3]
            T[:, 1, 2] = T[:, 2, 1] = E[:, 4]
            T[:, 0, 2] = T[:, 2, 0] = E[:, 5]
            grid.point_data["v"] = 100 * np.linalg.eigvalsh(T)[:, -1]
            title = "strain % (top = across-layer limit)"
            clim = (0, 100 * case["eval"].get("strain_allow_z", case["eval"]["strain_allow"]))
        diag = np.linalg.norm(np.ptp(z["nodes"], axis=0))
        umax = np.linalg.norm(z["U"], axis=1).max()
        scale = 1.0 if (case["nonlinear"] or umax > 0.03 * diag) else 0.06 * diag / max(umax, 1e-12)
        lin = grid.linear_copy()
        surf = lin.warp_by_vector("U", factor=scale).extract_surface(algorithm="dataset_surface")
        ghost = lin.extract_surface(algorithm="dataset_surface")
        p = _plotter(1400, 900)
        from matplotlib.colors import LinearSegmentedColormap
        cmap = LinearSegmentedColormap.from_list("forge", ["#5d6f82", "#3f8fc4", "#2ec4b6", "#ffd166", "#ff7b54", "#e63946"])
        p.add_mesh(surf, scalars="v", cmap=cmap, clim=clim, smooth_shading=True, split_sharp_edges=True, specular=0.3,
                   scalar_bar_args={"title": title, "color": "#dfe6ec", "vertical": True, "fmt": "%.2f",
                                    "position_x": 0.87, "position_y": 0.18, "height": 0.64, "width": 0.04})
        if scale != 1.0:
            p.add_text(f"deformation x{scale:.0f}", position="lower_left", font_size=12, color="#9fb0c0")
        # zoom: flexures on the loaded region (where the action is), strength cases on the whole part
        if case["use"] != "static":
            ctr = z["nodes"][z["load"]].mean(axis=0)
            near = np.linalg.norm(z["nodes"] - ctr, axis=1) < 0.35 * diag
            focus = pv.PolyData(z["nodes"][near])
            v = np.array([1.0, -1.1, 0.5]) * (np.sign(ctr[0]) or 1.0) * np.array([1, 1, 0]) + np.array([0, 0, 0.5])
            _frame(p, [focus], view=tuple(v), zoom=1.25)
        else:
            _frame(p, [ghost], view=(1, -1.3, 0.8), zoom=1.1)
        f = out / f"fea_{case['name']}.png"
        p.screenshot(f)
        p.close()
        files[f"fea_{case['name']}"] = str(f.relative_to(proj.dir))
        # force-deflection curve
        cv = np.asarray(case["curve"])
        if len(cv) > 2:
            fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=160)
            fig.patch.set_alpha(0)
            ax.set_facecolor("none")
            ax.plot(cv[:, 0], cv[:, 1], color="#2ec4b6", lw=2.2, marker="o", ms=3.5)
            ax.fill_between(cv[:, 0], cv[:, 1], color="#2ec4b6", alpha=0.12)
            ax.plot([0, cv[1, 0] * (len(cv) - 1)], [0, cv[1, 1] * (len(cv) - 1)], ls="--", color="#8a99a8", lw=1,
                    label="linear (first-step stiffness)")
            ax.annotate(f"{cv[-1, 1]:.1f} N @ {cv[-1, 0]:.2f} mm", xy=cv[-1], xytext=(-110, 12), textcoords="offset points",
                        color="#8a99a8", fontsize=9)
            ax.set_xlabel("deflection along load (mm)", color="#8a99a8")
            ax.set_ylabel("force (N)", color="#8a99a8")
            for s in ax.spines.values():
                s.set_color("#8a99a8")
                s.set_alpha(0.4)
            ax.tick_params(colors="#8a99a8")
            ax.grid(alpha=0.15)
            ax.legend(frameon=False, labelcolor="#8a99a8", fontsize=8)
            fig.tight_layout()
            f = out / f"curve_{case['name']}.png"
            fig.savefig(f, transparent=True)
            plt.close(fig)
            files[f"curve_{case['name']}"] = str(f.relative_to(proj.dir))
    return files


def render_all(proj: Project, turntable: bool = True) -> dict:
    out = proj.build_dir / "renders"
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    files.update(hero(proj, out, turntable=turntable))
    files.update(section(proj, out))
    files.update(motion_gif(proj, out))
    files.update(print_views(proj, out))
    files.update(fea_views(proj, out))
    proj.save("render", {"status": "pass", "files": files})
    return files
