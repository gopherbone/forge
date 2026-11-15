# Journal: Frog Automaton concept a

- **2026-11-15 00:32:26** 🧭 `agent` — Concept A topology, 7 parts: base (pond ring, open top+bottom), body (deck plate + lower jaw + hinge tab + fly on stalk), head (upper jaw + eyes), pin, tongue (cam follower), cam (one eccentric + hub), shaft (with crank arm + knob).

- **2026-11-15 00:32:26** 🧭 `agent` — One eccentric (e=4) drives a flat-footed follower in a bore inclined 28 deg towards the fly. The follower's round top IS the tongue and pushes the head's flat palate, so jaw and tongue are in phase by construction. Closed-form: s = e cos(theta) + R + 0.1; head angle from A sin a + B cos a = K. Gaps of 0.1 mm at both contacts at every angle.

- **2026-11-15 00:32:26** 🧭 `agent` — Base is a ring (no deck) and the deck is a plate moulded on the frog body, resting on a 45-deg ledge. Reason: an open-bottom box with a deck would need support for the deck ceiling or force an upside-down print that kills the lily-pad relief and locating features.

- **2026-11-15 00:32:26** 🧭 `agent` — Head pivots on a separate pin through a tab at the back of the body. Pin is snug in the head (long engagement, retention) and loose in the tab (free rotation); it deviates from the brief's head-pin loose suggestion for axial retention. Pin ends sit in recessed tympanum spot faces on the head sides.

- **2026-11-15 00:32:27** 🧭 `agent` — Shaft, crank arm and knob share one full-length D-flat plane (1.0 deep) so the shaft prints lying down; the cam hub runs to the +X bearing boss so a pull on the crank cannot draw the shaft out (cam is snug on the D-flat). crank_deg=0 is fully open (hero pose), 180 closed.

- **2026-11-15 00:32:27** 🧭 `agent` — base_w cut from 70 to 62 so the external crank keeps the footprint under 80 mm. Measured union bbox over a full turn: 75.5 x 51.6 x 60.9 mm (R1).

- **2026-11-15 00:32:27** 🧭 `agent` — All sphere poles are trimmed by 0.02 mm: exposed OCC sphere poles tessellate into non-watertight fans and failed the manifold check.

- **2026-11-15 00:43:29** 🧭 `agent` — Correction to the earlier R1 note: after head_rz 12 -> 14 the union bbox over a full turn (every 30 deg) is 75.5 x 51.6 x 62.5 mm, inside 80 x 60 x 90. The knob orbits ~1 mm above the desk.

- **2026-11-15 00:43:29** 🧭 `agent` — Lower lip carries a clean notch (box cut, stops notch_margin past the chin) where the tongue tip rests; the swept groove alone left a 0.14 mm2 sliver island. Tongue tip raised (tip_dz 3) so the notch is shallow.

- **2026-11-15 00:43:29** 🧭 `agent` — Side-face lily pads are flattened ellipses with a narrow notch: round notched pads on a vertical face read as letters ('3', 'C') in the hero render.

- **2026-11-15 00:50:23** 🧑 `human` — User rule from chat: 'avoid rounded edges coming off the build plate. they don't print well' and 'you should really think through those kinds of things, other 3d printing footguns'. Now enforced by forge check (bed_edge + feature footgun checks).
