# Journal: Frog Automaton concept b

- **2026-11-15 00:15:15** 🧭 `agent` — Architecture: 9 parts (base, crankshaft, camblock, 3 followers, 3 frogs). A one-piece frog can't be captured in a closed guide (frog above and foot-stop below both exceed the hole), so each frog presses onto its follower's keyed rod tip (snug socket, no flexure, so R8 is not triggered). One over the brief's ~6-8 parts.

- **2026-11-15 00:15:15** 🧭 `agent` — Base is one open-bottom piece printed deck-down (orient 180,0,0): deck-up would make the 59x45 mm deck a ceiling. So the pond face is flat on the textured plate and lily pads/notches/ripples are 45-degree V-grooves (no ceilings). Raised green pads would need a separate deck part (+1).

- **2026-11-15 00:15:15** 🧭 `agent` — Kinematics: eccentric round cams (e=3.5, R=8.5, stroke 7 mm) under flat feet; foot z = shaft_z + e*sin(phi_i + crank_deg) + R + 0.1, phases phi_i = 90-120i so frog i peaks at crank 120i (left-to-right wave).

- **2026-11-15 00:15:16** 🧭 `agent` — Stack sets base_h=42: shaft_z 17 (knob clears desk by 1.5 mm with crank_r 12, knob 7) + e + R + 0.1 gap + 2.4 foot + 1.5 stop gap + 9 mm guide (deck + sleeve, ~2x rod width so the 4x5 keyed rod can't cock).

- **2026-11-15 00:15:16** 🧭 `agent` — Crankshaft one piece, D-flat full length; hub/arm/knob cut on the D-flat plane so it prints lying flat (stronger shaft in bending than printed upright). Camblock printed on its -X disc with 45-degree cones under the upper two discs; cam_r >= e + hub_r keeps cones inside each disc's outline so feet never touch them.

- **2026-11-15 00:15:16** 🧭 `agent` — Frog sculpted from pole-trimmed ellipsoids (OCC tessellates sphere poles non-manifold; 0.01 mm trim fixes the watertight check). Belly cut at <= rz/sqrt(ry^2+rz^2) of each ellipsoid so undersides stay >= 45 deg. Rocking/tilt skipped for the concept.

- **2026-11-15 00:15:16** 🧭 `agent` — Axial retention: crank hub (0.4 mm off +X wall) stops the shaft going -X; camblock end (0.6 mm off the +X bearing rib) stops it pulling out +X, as long as the snug D-fit holds the camblock on the shaft.

- **2026-11-15 00:22:28** 🧭 `agent` — Reeds made bolder (3.0 wide, 1.6 proud, 24 tall) after the first hero render: at 2.2 x 1.2 they read as scratches. Leaf tips taper with edges steeper than 45 deg so they print deck-down without support.

- **2026-11-15 00:32:57** 🧭 `agent` — Front feet moved back/lengthened (hand ry 3.2, cy -6.8): they only grazed the body (~1 mm lens junction), below the 1.2 mm feature rule and not drop-proof. Now ~3 mm junction.

- **2026-11-15 00:32:57** 🧭 `agent` — pad_rx 9.6 -> 9.2 to leave ~1.2 mm of deck between neighbouring pad grooves; ripples centred on the deck corner radius centre so they clear the perimeter chamfer; default crank_deg 30 so the hero shows high/middle/low frogs.

- **2026-11-15 00:32:57** 🧭 `agent` — Crankshaft bed outline (D-flat plane) chamfered 0.4 against elephant foot. Frog belly left unchamfered: the ellipsoid meets the bed at ~45 deg already.

- **2026-11-15 00:50:23** 🧑 `human` — User rule from chat: 'avoid rounded edges coming off the build plate. they don't print well' and 'you should really think through those kinds of things, other 3d printing footguns'. Now enforced by forge check (bed_edge + feature footgun checks).
