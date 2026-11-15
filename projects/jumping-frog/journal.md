# Journal: Jumping Frog

Decisions, findings and human comments, newest last.

- **2026-11-15 03:41:29** 📝 `forge` — project created

- **2026-11-15 03:41:44** 🧑 `human` — Brief from chat: 'really simple one: do a printable jumping frog. simple, clever design please'.

- **2026-11-15 03:41:44** 🧭 `agent` — Concept (lead): one part, extruded side-profile silhouette printed on its side, with the hind leg as an in-plane curved spring under the body. Press and slide off to jump. Verify with nonlinear FEA (strain, force-deflection, stored energy → hop-height estimate). Stretch goal: a self-latching catch.

- **2026-11-15 03:50:38** 🧭 `agent` — Profile = one 2D face (body+head, eye ring, front leg, sole, C strip) extruded once; all rounding is 2D vertex fillets so print-side faces have no rounds/chamfers (CLAUDE.md wall-meets-plate rule).

- **2026-11-15 03:50:38** 🧭 `agent` — Spring = C strip t=1.8 (4.5 lines), two R4 bends + 6 mm straight back (~19 mm arc + 4 mm straight before the rump), joining a 3 mm flat sole. forge flex hinge L=18.6 t=1.8: 15 deg -> 1.27% strain (util 0.63 repeated). Root fillets R2 at both ends; the sole rear ramps into the strip so the lower root is obtuse.

- **2026-11-15 03:50:38** 🧭 `agent` — Hard stop = the front leg: its flat toe sits stop_gap=5 mm above the hind foot (sole). The finger land is the flat back directly above the toe, so press travel ~= toe travel. Eye = 5 mm through-hole in a 2 mm ring bump; smile = 1 mm through-slit from the snout (shows on both faces, prints as vertical walls).

- **2026-11-15 03:53:12** 🧭 `agent` — Spring t 1.8 -> 2.0 (5 lines) and stop_gap 5 -> 6: energy scales ~t^3 x travel^2 and strain ~t x travel, so this spends the unused strain margin on energy (aim util ~0.65, ~16 mJ, ~5 N).

- **2026-11-15 03:54:51** 🧭 `agent` — spring_h 6 -> 7.5 so the front leg keeps a visible 4 mm below the belly with the larger stop gap. FEA (fast): toe closes 5.87 of 6.0 mm at 6.2 mm finger travel (front toe corner lands first), so press_travel = 6.35 mm puts the toe on the sole.

- **2026-11-15 03:56:44** 🧭 `agent` — Eye hole first-layer warning accepted: the 5 mm eye is cosmetic (nothing fits in it), so elephant foot only softens its plate-side edge. A stepped relief would put a visible step on the plate-side show face.

- **2026-11-15 03:56:44** 🧭 `agent` — R6 latch NOT done. Holding the ~5 N spring needs a felt catch (>= 1 mm engagement, 5-15 N per the snapbox test), which means a second flexure (sole-tip barb or toe hook) tuned against the main spring, plus a tail lever to pull it clear. That doubles the mechanism and needs a physical test to tune hold vs release. Candidate for v2: barb on the sole tip catching a notch in the front toe, released by pressing the snout.

- **2026-11-15 04:07:20** ✅ `agent` — Full run (build 34991fbb): spring case 4.87 N at 6.35 mm finger travel (toe on the sole), 16.2 mJ stored, peak strain 1.25% (util 0.62 repeated, in-layer; across-layer 0.41% vs 1.2%), SF 2.37; mesh convergence 0.2% peak / 0.1% force (0.43 mm, 56k el). Hop estimate h = 0.3 x 16.2 mJ / (6.66 g slicer mass x g) = 74 mm (R4 >= 30 mm). Slice 16m05s, 6.66 g, 0 support. Assumptions: 30% energy-to-height efficiency, sole clamped, no contact, isotropic E=1460 MPa (low-confidence material).

- **2026-11-15 04:09:58** ✅ `agent` — FEA v1 (t=1.8, spring_h 6, 5 mm press, fast mesh): 3.1 N, 8.2 mJ, peak strain 0.97% (util 0.49) on the outer fibre of the C's straight back, not at the roots. Hop ~38 mm: marginal, so the unused strain margin was spent on energy.

- **2026-11-15 04:10:01** ✅ `agent` — R5 confirmed on the full-run field (34991fbb): at 6.35 mm finger travel the front toe's leading corner reaches z=2.998 (sole top 3.0), so the stop closes at util 0.62. No spring self-contact; belly stays >= 4.3 mm off the table.

- **2026-11-15 04:22:27** 🧭 `agent` — Reviews in. Print engineer (G-code, every layer): ready to print. The spring is solid (2 loops per side + a gap-fill core, all beads along the strip), seams hidden in the eye bore and smile end, eye hole widened by the slicer's elephant-foot compensation. Critic: the silhouette reads partly as a stapler; fix the smile lip sliver and the notch behind the front leg; release ridge at the rump; optional shorter webbed foot + knee bump. Spec wording corrected: '3 walls' → '2 loops per side + gap-fill core = solid'.

- **2026-11-15 04:23:14** 🧑 `human` — User (chat): 'Polish, then print'. Lead's consolidated change list: close the smile before the snout tip, remove the notch behind the front leg, rake the front leg forward, add a rump release ridge, shorten the sole into a webbed foot with V toe notches, add a knee bump outside the bending zone. Re-verify everything.

- **2026-11-15 04:24:01** 🚦 `human` — approved gate **spec**

- **2026-11-15 04:24:17** 🚦 `human` — approved gate **concept**

- **2026-11-15 04:27:50** 🧭 `agent` — Polish pass (critic list): smile is now a closed 1 mm slit with round ends, 7.5 mm long, stopping 1.5 mm inside the snout tip (no lower-lip sliver). Eye/head layout decoupled from the smile via new head_len=9, so the head shape is unchanged.

- **2026-11-15 04:27:50** 🧭 `agent` — Front leg: rear edge rakes forward 3.5 mm straight out of the sloping belly (the flat belly step behind the leg, the 'notch', is gone), front edge vertical with R1.25 root. leg_x 21 -> 16.5 so the toe (x 20-25) lands on solid foot behind the toe notches.

- **2026-11-15 04:27:50** 🧭 `agent` — Rump release + knee: the rump wall is now vertical, topped by a R2.5 half-round knee ridge at the rear of the flat back. A finger sliding back rides over it and drops off a 9 mm vertical step clear of the spring loop. The knee sits on the rigid body, NOT on the spring: the FEA field shows the C's outer fibre at 1.0-1.25% along its whole length (bends and back alike; only the straight inside the rump falls to 0.4%), so there is no low-strain spot on the bend for a bump; any bump there would stiffen it and add a stress raiser.

- **2026-11-15 04:27:50** 🧭 `agent` — Hind foot: sole_end 36 -> 30 with 2 V toe notches (1.4 deep, 2 mm pitch) = a 3-toed webbed foot. COM x 23.6 vs foot contact x ~5-28.6: stands without tipping; the finger line (x 22.5) is inside the foot too. stop_gap 6 -> 5.5 because the stop moved closer to the spring (shorter lever = more rotation per mm). FEA fast: toe closes at press_travel 5.8 mm, util 0.67, 5.8 N, 17.8 mJ.

- **2026-11-15 04:27:50** 🧭 `agent` — Spec wording: spring_t comment now says it prints as 2 loops per side + gap-fill core = solid (print engineer, G-code).

- **2026-11-15 04:40:50** 🧭 `agent` — Toe tips between the V notches got R0.25 fillets: clears the 117 deg sharp-corner warning at the plate. The closed smile slot now trips small-vertical-hole (1.0) and first-layer-hole (3.4 equiv) warnings, which the open slit did not. Accepted for now: the earlier 1.0 mm slit printed clean in the G-code review; the human should check the plate-side smile on the first print (fallback: mouth_w 1.2).

- **2026-11-15 05:11:05** ✅ `agent` — Polish full run (build a9a33c6b): toe notch width 1.0 with R0.45 tips (the R0.25 tips gave CalculiX a nonpositive-jacobian element). Spring: 5.79 N at 5.8 mm, toe reaches z 2.986 (stop closes), util 0.67 (peak 1.33%, across-layer 0.43%), SF 2.22, 17.7 mJ, convergence 0.3%. Hop 0.3 x 17.7 mJ / (7.06 g x g) = 77 mm. Slice 17m10s, 7.06 g, 0 support. Warnings: closed 1 mm smile slot (small vertical hole + first-layer hole) and the 5 mm eye.

- **2026-11-15 05:13:06** 🧭 `human` — User decision (chat 'sure'): the spec gate now binds to requirements/loads/materials/constraints only, not params or printer settings. Dimension changes are still reviewed at the print gate. The existing spec approval used the old whole-file hash, so it needs one re-approval.

- **2026-11-15 05:13:55** 🧑 `human` — User (chat): 'i approve all of those' (spec re-approval, print, release). Waiting for the terminal approval records; the lead runs release after they exist.

- **2026-11-15 05:14:08** 🚦 `human` — approved gate **spec**

- **2026-11-15 05:14:16** 🚦 `human` — approved gate **print**

- **2026-11-15 05:14:20** 🚦 `forge` — released build a9a33c6b39: jumping-frog_plate1-a9a33c6b.3mf
