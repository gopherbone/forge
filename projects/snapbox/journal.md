# Journal: Snapbox

Decisions, findings and human comments, newest last.

- **2026-11-14 22:57:51** ⚠️ `agent` — hook_snap FAILED v1: FEA peak strain 3.08% (2.97% across layers vs 1.2% allowable, repeated use). Peak at the sharp arm root where the arm meets the lid plate; beam theory predicted only 0.84%, so the root corner is a ~3x concentration.

- **2026-11-14 23:00:00** 🧭 `agent` — Root cause of the 3x gap vs beam theory was my load case, not the solver: loading the whole lip face locked the tip rotation (guided beam). Changed to a line contact and excluded nodes within 1 mm of the load. True v1 peak: 1.49% at the root, 1.24x the across-layer allowable. Still fails.

- **2026-11-14 23:00:00** 🧭 `agent` — v2: hook arm 14 → 18 mm, lip 0.7 → 0.6 mm, 0.4 mm root fillet. Beam theory predicts root strain ×0.5.

- **2026-11-14 23:23:31** 🧭 `agent` — Correction: the line-contact fix was only part of it. Prescribing displacement on every contact node still locked rotation locally (bare-beam control: 2.8x too stiff vs beam theory). FEA now uses a distributing coupling (reference node tied by *EQUATION to the average contact displacement), validated to within 8% of force control and 15% of beam theory (new regression test). Earlier hook results were conservative: strain overstated, force wrong.

- **2026-11-14 23:38:36** 🧭 `agent` — Final peak strain sits at the centre of the hook root on the 0.4 mm fillet (0.60%), not the slot corners. The 13% convergence drift means that fillet is under-resolved. Next step: 0.8 mm root fillet or a finer root mesh.

- **2026-11-14 23:54:23** 🧑 `human` — User is printing the box (from chat: 'also i'm printing the box'). Printed before the print gate / release, so this is a test print of build 3e90e256fe.

- **2026-11-15 00:52:37** 🧑 `human` — TEST PRINT FEEDBACK (user, verbatim): 'the edges did cause a warping/curling issue. the overhang isn't a great conformant design, it doesn't really add any more click-into-place tactility than the layer lines do'

- **2026-11-15 00:52:54** 🧑 `human` — User (verbatim): 'that said the print is otherwise quite strong'

- **2026-11-15 00:53:40** 🧭 `agent` — Lesson from the physical test: a 0.6 mm lip (0.4 mm engagement ≈ 2 layers) at ~0.9 N simulated push gives no tactile click; it feels like layer lines. A felt snap needs a larger undercut (≥ 1 mm, ≥ 5 layers), a defined catch face, and roughly 5-15 N push. The 45° bed-edge chamfers passed the new check, yet the user saw curling: which edges is pending.

- **2026-11-15 00:55:37** 🧑 `human` — User (verbatim): 'on the snap hook lips, they didn't really curl so much as they didn't protrude enough outward to really make a difference.' Root cause: lip 0.6 mm minus 0.2 mm skirt gap = 0.4 mm engagement, a ~2-3 layer feature that the as-printed rounding shrinks further.
