# Mutilated pinion (movement 114): designer hand-back, pre-print pass

**Build ea90883a35, all stages current** (`forge status`, 2026-11-15 09:50):
| Stage | Status |
|---|---|
| build | pass |
| orient | pass |
| check | warn |
| fit | pass |
| sim | pass |
| physics | warn |
| slice | pass |
| render | pass |
| report | warn |

There are no fails. 7 parts, 1h36m (Bambu estimate), 38.1 g PETG, 0% support.

## What changed in this pass

### 1. Seams moved off the snap and fillet roots (confirmed in the G-code)
- **Notches alone did not work.** I added sharp V-notches, vertical in print: one on each post's back (+Y) face between the prong roots and the rod hole, and one on the crank arm's back face. With `seam_position = aligned` the slicer still put every post seam on the slit tops at z = 19 (the snap roots) and the crank seam on the shaft/hub shoulder. That held at a 90° notch and again at a sharper 60° (0.6 mm deep). Aligned seams prefer the deep, hidden slit tops.
- **Fix:** `seam_position: back` in the `printer.overrides` block of spec.yaml (G-code header confirms `; seam_position = back`). The 60° notches stay; they now act as the anchor on the back face.
- **Confirmed locations:** outer-wall start points from each part's `build/slice/<part>/out/plate_1.gcode`, mapped back to the part frame.

| Part | Outer wall | Inner contour | Snap / fillet roots |
|---|---|---|---|
| post_l, post_r | back face y = 3.0, z = 20.0: the V-notch (39 of 39 layers) | rod hole, back edge | none |
| crank | knob end face, y = 23 (all layers) | n/a | none on the hub/arm fillet (y = 8.3) or the shoulder |
| pinion | top of the plain toothless arc (z ≈ 9.5) | top of the bore | none on teeth |
| frame | top-bar outer edge (z = 18) | top-rack root corner (z = 13) | n/a |
| cap | cylinder side | counterbore | n/a |

The frame's window seam sits in a root corner, which has 0.375 mm tip clearance to the pinion, so it is not on a flank or tooth tip.

### 2. Catch lands at least one line wide
- **barb_land 0.4 → 0.6:** cap 7.4 → 7.6 mm, counterbore 2.0 mm, both on the 0.2 grid.
- **hook_land 0.4 → 0.5.**

### 3. Ledge on the layer grid
- **slot_len 2.5 → 2.4:** the ledge moves to z = 2.6.
- **New `catch_gap: 0.2`:** an explicit one-layer catch gap, so z_catch stays at 2.4.
- **Hook tip:** now at z = 0.17. The 30° lead-in is unchanged.

## Before → after

| | bab327f13c (before) | ea90883a35 (after) |
|---|---|---|
| crank_push, FULL mesh | SF 2.59, conv 2.8% | **SF 2.43, conv 8.9% (pass, < 10%)**, 258,684 nodes |
| crank_push, fast | 2.67 | 2.66 |
| post_snap (fast) | 6.27 N, strain 66% | 6.22 N, strain 66.5% |
| cap_snap (fast) | 5.64 N, strain 73% | 5.45 N, strain 71% |
| Fits / sweep | pass | pass: mesh 0.242 at crank 90, sweep min 0.143, travel 29.26 |
| Print | 1h35m, 37.8 g | 1h36m, 38.1 g |
| Seams (posts / crank) | aligned: on snap roots / shoulder | back: on the post notch / knob end |

The full-mesh crank SF fell 2.59 → 2.43, presumably the arm-back notch; I did not locate the new peak. It still clears 2 and has converged.

## Remaining warnings (unchanged, with reasons)
- **`first_layer_holes`**, on the pinion and cap bores, the post rod holes and the plinth hook pockets. These through-holes have to exist; slicer hole compensation is on, per the print review.
- **`small_vertical_holes`**, on the post slits (0.8 / 2.6) and the crank slit (1.4). These are open flexure slots, each with ≥ 0.3 mm over its deflection.
- **Crank `up_curves`:** the shaft has to be round to run in its bearing.
- **Physics:** "drive stalled" (warn). This is expected for gear teeth on convex hulls. R8 is a human hand test.

## For a human
1. With the seam at the back, the frame's top edge and the cap's cylinder side carry seams. Both are out of the front view.
2. In the elevated hero view, the crank knob shows above the frame at crank 90°. Straight-on it is hidden.

## Unchanged from the previous pass
- Everything else: m1.5 z15, 5 kept teeth, 14.5° pressure angle, 29.26 mm travel each way, snaps, screen, band, window.
- The R3/R4 scratch evidence (B-rep sweep, capture study, post stop at 2.28 mm) still applies: the mesh geometry did not change.

Full reasoning is in journal.md. I did not run `forge approve` and touched no other project.
