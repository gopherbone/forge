# Movement 84: kinematic and force audit (lead, 2026-11-15)

Sources: Brown 1868 fig. 84 (reference/brown-1868-movement-84.png; https://507movements.com/mm_084.html),
reproduced in the 507-movements PDF (nakka-rocketry.net). A secondary write-up (firgelliauto.com, partly
auto-generated) cites Hiscox fig. 995 as the same ratchet-governor idea. No source gives forces, so
everything below is derived. All numbers are design targets; FEA and the sweep must confirm them.

## 1. What each part must do (degrees of freedom)
| Part | Free | Held by | Notes |
|---|---|---|---|
| B (frame) | X translation (the output) | Y and the rotations: its two END RODS in the post bearings. Z: A's pins | Z is not free: it's SET by A. B must not rock in its plane |
| End rods (part of B, as drawn) | move with B in X and Z | post bearings: vertical slots (front/back held, Z free by the selector stroke) | Literal 1868 arrangement. It fits in 120 mm once D is small (see 4) |
| A (selector) | Z (3 positions) | guide on a bracket; detent | Its fork pins ride in B's top slot. B slides in X under them |
| D (cam) | rotation about Y | shaft in the pedestal bearing | One-way crank (sawtooth) |

## 2. Why the v2 model didn't make sense
1. Fixed rods poked into B's window. Not the engraving, and confusing to read.
2. B's rocking in its plane was held only by two pins 10 mm apart in a slot with 0.4 mm clearance: ±0.04 rad. That's the same order as the 1.8 mm blade penetration once you're out at the frame ends.
3. Vertical forces from each blade strike were never quantified.
4. Detent and guide hardware cluttered the top and made it asymmetric.
5. A big cam (R11, pitch 6.5, 4 teeth) forced a big frame, which forced the hidden-rod compromise.

## 3. Free-body diagram of B during a push (selector UP, lower rack engaged)
Forces on B:
- Blade tip on a steep (vertical) tooth face: normal force **N, horizontal (+X)**, the drive.
- Friction at that contact: **±μN, vertical** (the blade tip slides along the face as it sweeps). μ ≈ 0.3.
- A's pins: vertical reaction R_A (B's weight + friction), plus a couple from two pins at spacing s (resists in-plane moment).
- Rod bearings: friction μ·(normal) in X, and Y reactions (no Y loads in normal use).
- Gravity: m_B·g (B + rods ≈ 10 g → 0.1 N).
Required drive force: N ≈ friction at the pins and rods (μ·0.1 N ≈ 0.03 N) + inertia (≈ 0) → **N < 0.5 N** with margin.
- Vertical disturbance on A: |μN| ≤ 0.15 N vs detent holding force ≥ 5 N → **> 30× margin**.
- In-plane moment: N acts at the rack line, ~h = 15-20 mm below the pins → M ≈ N·h ≈ 10 N·mm, reacted by the pin couple M/s.
- Rocking clearance: pin/slot gap g = 0.2 mm per side → tilt ≈ 2g/s. With **s ≥ 24 mm** the tilt is ≤ 0.017 rad, i.e. ≤ 0.2 mm at the engaged tooth (≤ 12 mm from centre). Acceptable against a 1.6 mm penetration.

## 4. Drive geometry (CORRECTED after advisor review + 2D contact study, study_2d.py)
The first version of this section was wrong: it gave the rods' static length rather than the swept width,
claimed one tooth per blade without checking it, and treated the blade as a point. Replaced by solver results:
- Study: real 2 mm blades, 4-blade cam, push-only frame (B is free in X), selector UP, engagement depth
  d = 0.9 (worst tolerance) / 1.6 (nominal) / 2.0 (deep) mm. Figure: reference/drive_study.png.
- **Pitch p ≤ 5 mm RUNS AWAY** (the blade's sweep covers more than one tooth and shoves B through
  several) for R 6-8 mm. **p = 6 mm is robust**: every blade advances B exactly one tooth (6 mm)
  then pauses, at all three depths. That's 24 mm per crank turn.
- Chosen: **cam R = 7 mm, 4 blades 2.0 mm thick, sawtooth p = 6 mm, tooth height 3 mm**, neutral clearance
  c = 1.0 mm (solver: 1.0 mm gap over a full turn), engaged depth d = 1.6 mm, selector stroke S = 2.6 mm.
- Travel per direction must be a whole number of teeth: T = 6 mm (1 tooth) or 12 mm (2 teeth).

## 4b. Width (swept envelope, not static length)
The end rods move with B through bearings on fixed posts. A rod must stay in its bearing at -T and
clear the frame at +T, so it needs length ≥ 2T + gap + bearing. Swept width ≈ 2F + 6T + 2(gap + bearing),
where F = frame half-length (cam R + T + rack run-out + rim ≈ 23-28 mm).
- T = 6 mm (1 tooth each way): ≈ 50 + 36 + 14 = **~100-110 mm**, fits 120.
- T = 12 mm (2 teeth each way): ≈ 56 + 72 + 14 = **~140 mm**.
- T = 12 mm in 120 mm is only possible with FIXED rods poking into B's window (the v2 compromise the user rejected).
This is a user decision (it was "120 mm, ~12 mm travel" before these numbers were known).

## 5. Tolerance stack on engagement
Engagement depth band d = 0.9-2.0 mm was solved explicitly (above): clean one-tooth steps at both
ends. Neutral: c = 1.0 mm nominal, ≥ 0.3 mm at worst stack. forge's 3D sweep only runs at nominal,
so the tolerance-extreme evidence is this 2D study, labelled as such.

## 6. Failure modes (corrected)
- **B is free in X between pushes** (only friction holds it). That's acceptable for a model; add a light
  drag (a slight interference wiper on one rod bearing, ~0.2 N) so B doesn't drift when handled.
- **Reverse cranking (corrected):** B is free in X, so the blades ride the 30° back slopes and drive B
  backwards roughly instead of jamming. The contact normal on the slope puts ~1.7× the (tiny, < 0.5 N)
  drive force vertically into A's detent, far below its 5-15 N hold, so the selector stays put. Smooth
  forward, rough reverse, no damage (estimated; x-only solver, so a human checks it).
- **Over-travel:** D runs off the last tooth. Rod shoulders against the bearings are hard stops for hand-pushing.
- **Selector between notches:** the V-notch flanks cam A into the nearest position.

## 7. What forge must verify
- Sweep (drives=True): engagement at UP and DOWN; neutral clearance > 0 at both tolerance extremes; no undeclared contact.
- FEA: detent (5-15 N, strain); crank push; a blade-root bending check at N_max = 2 N (10× margin is trivial, but prove it).
- Physics: not validated for this type, so exploration only.
