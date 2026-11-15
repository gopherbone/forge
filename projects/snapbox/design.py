"""Snapbox: base + snap-fit lid. Both parts are modelled in the assembly frame
(base floor at z=0, lid plate sitting on the rim at z=H), so part frame = assembly frame."""
from build123d import *

from forge.config import fits_table
from forge.dsl import Design, Fit, LoadCase, Part, Region


def build(p) -> Design:
    W, D, H, t = p.width, p.depth, p.height, p.wall
    g = fits_table()["sliding"]["gap"]  # skirt-to-wall clearance per side

    # ---------------- base ----------------
    base = extrude(RectangleRounded(W, D, p.corner_r), H)
    base -= Pos(0, 0, p.floor) * extrude(RectangleRounded(W - 2 * t, D - 2 * t, p.corner_r - t), H)
    # windows for the hook lips, through the two end walls
    lip_z0 = H - p.skirt_h                    # lip bottom (arm tip)
    lip_z1 = lip_z0 + p.lip_ramp + p.lip_h    # lip catch face
    wz0, wz1 = lip_z0 - p.win_clear, lip_z1 + p.win_clear
    for sx in (1, -1):
        base -= Pos(sx * (W / 2 - t / 2), 0, (wz0 + wz1) / 2) * Box(t * 3, p.win_w, wz1 - wz0)
    base = base.chamfer(p.edge_chamfer, None, base.edges().group_by(Axis.Z)[0])
    base = base.fillet(0.5, base.edges().group_by(Axis.Z)[-1])

    # ---------------- lid ----------------
    lid = Pos(0, 0, H) * extrude(RectangleRounded(W, D, p.corner_r), p.lid_t)
    lid = lid.chamfer(p.edge_chamfer, None, lid.edges().group_by(Axis.Z)[-1])  # top edge: on the bed when printed
    sw, sd, sr = W - 2 * t - 2 * g, D - 2 * t - 2 * g, p.corner_r - t - g
    st = p.skirt_t
    skirt = Pos(0, 0, H - p.skirt_h) * extrude(RectangleRounded(sw, sd, sr), p.skirt_h)
    skirt -= Pos(0, 0, H - p.skirt_h - 1) * extrude(RectangleRounded(sw - 2 * st, sd - 2 * st, max(sr - st, 0.6)), p.skirt_h + 2)
    # free the hook arms: two slots per end, from the skirt bottom up to the plate
    for sx in (1, -1):
        for sy in (1, -1):
            y = sy * (p.arm_w / 2 + p.slot / 2)
            skirt -= Pos(sx * (sw / 2 - st / 2), y, H - p.skirt_h / 2 - 0.5) * Box(st * 3, p.slot, p.skirt_h + 1)
    lid += skirt
    # hook lips: lead-in ramp then a flat catch face
    xo = sw / 2
    prof = Polygon((xo - 0.01, lip_z0), (xo + p.lip_u, lip_z0 + p.lip_ramp), (xo + p.lip_u, lip_z1), (xo - 0.01, lip_z1), align=None)
    lip = extrude(Plane.XZ * prof, p.lip_w / 2, both=True)
    lid += lip
    lid += lip.mirror(Plane.YZ)
    # root fillet where each arm meets the plate: the sharp inside corner was the peak-strain spot
    root = [e for e in lid.edges().filter_by(Axis.Y)
            if abs(e.center().Z - H) < 1e-3 and abs(abs(e.center().X) - xo) < 1e-3 and abs(e.center().Y) < p.arm_w / 2 + 1e-3]
    if p.root_fillet > 0:
        if len(root) != 2:
            raise ValueError(f"expected 2 hook-root edges to fillet, found {len(root)}")
        lid = lid.fillet(p.root_fillet, root)

    # ---------------- relationships ----------------
    fits = [Fit("base", "lid", "sliding", region=Region((-W, -D, H - p.skirt_h - 1), (W, D, H - 0.3)),
                notes="Skirt inside the base walls. The lid plate rests on the rim (contact).")]
    # Load a LINE of contact on the lip face, as the base wall does. Loading the whole lip face
    # would also stop the arm tip rotating (a guided beam: 4x too stiff, 2x the root strain).
    zc = lip_z0 + p.lip_ramp + 0.5
    lip_region = Region((xo + p.lip_u - 0.05, -p.lip_w / 2, zc - 0.3), (xo + p.lip_u + 0.05, p.lip_w / 2, zc + 0.3))
    deflect = p.lip_u - g + 0.1
    plate_top = Region((-W, -D, H + 0.6), (W, D, H + p.lid_t + 1))
    rim = [Region((sw / 2 + 0.2, -D, H - 0.01), (W, D, H + 0.01)), Region((-W, -D, H - 0.01), (-sw / 2 - 0.2, D, H + 0.01)),
           Region((-W, sd / 2 + 0.2, H - 0.01), (W, D, H + 0.01)), Region((-W, -D, H - 0.01), (W, -sd / 2 - 0.2, H + 0.01))]
    loads = [
        LoadCase("hook_snap", "lid", fixed=plate_top, load=lip_region, displacement=(-deflect, 0, 0),
                 nonlinear=True, use="repeated", steps=8, mesh_size=0.45,
                 refine=Region((xo - st - 1.5, -p.arm_w / 2 - 3, lip_z0 - 1), (xo + p.lip_u + 1, p.arm_w / 2 + 3, H + 2)),
                 notes=f"+X hook arm pushed inward {deflect:.2f} mm (lip {p.lip_u} − gap {g} + 0.1 margin), "
                       "as when the lid goes on or is pressed open."),
        LoadCase("lid_press", "lid", fixed=rim, load=Region((-10, -10, H + p.lid_t - 0.01), (10, 10, H + p.lid_t + 0.01)),
                 force=(0, 0, -p.press_n), use="static", mesh_size=1.1, uniform=True,
                 notes="40 N on a 20 × 20 mm patch at the centre. Rim underside clamped (slightly stiffer than reality)."),
    ]
    return Design(
        parts=[Part("base", base, color="#2ec4b6", cosmetic=["+x", "-x", "+y", "-y"]),
               Part("lid", lid, color="#e8edf1", cosmetic=["+z"],
                    notes="Hook arms are vertical cantilevers. In any flat orientation they bend across layers.")],
        fits=fits, loads=loads,
        explode={"base": (0, 0, 0), "lid": (0, 0, 30)},
    )
