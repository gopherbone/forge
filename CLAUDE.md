# forge workspace: printable assemblies for a Bambu Lab X1C

This repo is a verifiable design-for-print pipeline. Designs are parametric build123d code. Every claim about a design comes from a tool that writes a hash-stamped result. The human signs off at gates. Start design work with the `/forge` skill.

## Layout
- `forge/`: the toolkit (CLI `.venv/bin/forge`). `forge/data/` holds materials, fit clearances and printability thresholds, each with a source and confidence.
- `projects/<name>/`: `spec.yaml` (requirements + params, human-approved), `design.py` (build123d, returns `forge.dsl.Design`), `journal.md` (decisions and human comments), `approvals.json` (gates, written only by `forge approve`), `build/` (generated, disposable), `release/` (approved 3MFs).
- `.claude/agents/`: forge-designer (edits geometry), forge-print-engineer (review only), forge-sim-engineer (load cases + FEA), forge-critic (aesthetics, read-only).
- `.tools/bin/ccx`: CalculiX copied from FreeCAD.app with its libgfortran rpath fixed (`make tools`).

## Hard rules
1. **Only the print gate is mandatory** (user: 'less stuff to approve'). Spec and concept are chat decisions logged in the journal. **Never approve a gate or fake an approval.** `forge approve` is human-only: it needs an interactive TTY. That's a guard rail, not a lock. Never run it, and never write `approvals.json`. Deny rules for both are proposed in `docs/claude-settings.proposed.json`, but not active unless the user installs them.
2. **Never send to a printer.** No Bambu cloud/LAN calls. `forge release` only copies files.
3. **Evidence kinds are not interchangeable.** verified = geometric/slicer fact · measured = sampled geometry · heuristic = rule of thumb · estimated = FEA or material data (confidence: low). Report them as such.
4. **A stale result is no result.** Results bind to the build hash. After editing `design.py` or `spec.yaml`, re-run before you quote numbers.
5. **Log decisions** with `forge note`. Human comments are logged in their words with `--author human --kind human`.
6. **Defaults:** PETG (Bambu PETG Basic), 0.4 nozzle, 0.20 mm Standard @BBL X1C, Textured PEI plate. Change them in a project's `spec.yaml` `printer:` block, not in code.

## Hard-won facts (don't relearn these)
- The Bambu Studio CLI does **not** resolve preset `inherits`. A raw system preset slices with a 200×200×100 bed, PLA and 0 g. `forge/printer.py` flattens presets (system, then user), sets `from: system`, and `slicer.assess` checks the G-code header matches. `--export-3mf` takes a bare filename, and the output dir must exist.
- FEA: gmsh tet10 → CalculiX C3D10 needs the last two edge nodes swapped (`GMSH_TO_CCX`). Validated against Timoshenko beam theory within 1.3% (`tests/test_fea_validation.py`).
- Load snap-fit lips on a thin **line** of contact. Loading the whole lip face locks tip rotation (guided beam: 4× stiffness, 2× root strain). Headline FEA numbers exclude fixed nodes and nodes within 1 mm (or 2 elements) of the load.
- Use `*NODE FILE, FREQUENCY=100000` (end-of-step only). Writing every NLGEOM increment produced 430 MB `.frd` files.
- Mesh locally (`LoadCase.refine` / `mesh_size`) or use `uniform=True`. A uniform fine mesh on a whole lid was 330k nodes and too slow.
- Flexures that bend across layers get ~60% of the in-layer strain allowance (`strain_allow_z_factor`). Prefer in-layer bending. Fillet flexure roots.

## Style rules from the user
- Zero supports by default (minimal at most, opt-in per part with a reason).
- Snap-together construction: no glue, no screws. Every Fit declares `retention` (snap with a verified `snap_case`, captured, or press). Snaps must be felt (≥ 1 mm engagement, 5-15 N).
- Simple and minimal: no rounded surfaces facing up (stair-stepping emphasises layer lines); flat tops, vertical walls, crisp silhouettes.

## FDM footguns (user-driven: "think through other 3D printing footguns")
Checked automatically by `forge check` (each one has a known-bad fixture):
- Convex **rounds or chamfers** on edges meeting the plate, domes, or undercut spheres (concave fillets and vertical-edge fillets are fine, and reduce warping). The user: 'rounded off edges are more of a problem than fillets'. **User rule, confirmed by a test print where 45° chamfers curled:** walls meet the plate vertically. Elephant foot is left to the slicer's `elefant_foot_compensation`.
- Round holes lying horizontal (the crown droops, so shafts bind): use a teardrop or flat-top hole, or orient the axis vertical.
- Pins and shafts printed upright (they snap along layers); small vertical holes < 3 mm (they shrink); holes through the first layer (elephant foot); slender towers; PETG stringing across spread islands; plus overhangs, bridges, walls, islands, adhesion and anisotropy.
- Sharp vertical corners on large footprints (corner lifting/warp): fillet edges normal to the bed (Markforged design tips).
- Thin horizontal gaps under a ceiling (< 3 layers): the bridge sags and welds the gap shut, e.g. a snap finger fused to its skin (`z_fuse`, automaton print review).
Not yet automated (from the automaton print review): Z features landing exactly on slice mid-planes (coin-flip heights), so keep Z values on 0.2 multiples; tips thinner than one line (0.42) on snap teeth print truncated; aligned seams on cam running surfaces bump the follower. Seams also land on snap roots and FEA peak fillets (114 print review): check seam positions against high-strain features. V-notches alone did NOT steer aligned seams (the slicer prefers deep slit tops); `seam_position: back` in printer.overrides plus a notch on the back face did (114, verified in G-code). But `back` is relative to the PLATE, and the slicer may rotate the part on arrange: on gator-clip a 53° rotation put 43 seams in the mouth, so `nearest` (seams hide in concave corners) won there. Always verify seams in the G-code after arranging. TODO toolkit: a deflected-flexure clearance check (FEA has no contact: the automaton frog snap finger hit its own cavity wall 0.1-0.36 mm before clearing, found by hand), so compare the deformed flexure against the rest of its part; an automated seam-vs-strain check; orient's sf_min disagreed with sim SF on 114 (investigate).
Not checkable from geometry, so designers and reviewers must think about them:
- Z features are quantized to the 0.2 mm layer: vertical gaps < 1 layer fuse; keep Z steps on layer multiples.
- Seam placement on show faces (aligned seams scar curved fronts; put them at the back or on a sharp edge).
- PETG: dry the filament (strings, blobs), no glue stick on textured PEI, and it bonds hard to smooth PEI (use the textured plate).
- Mating faces printed on the bed get the plate texture, which adds friction to sliding fits.
- Press fits along layer lines split the part. Put interference across layers, or use crush ribs.

## Physical test results (ground truth beats simulation)
- snapbox v2 test print: the parts are "quite strong". The 0.6 mm hook lip (0.4 mm engagement, ~0.9 N simulated push) gave **no felt click**: it's indistinguishable from layer lines. For a tactile snap, target ≥ 1 mm engagement (≥ 5 layers), a crisp catch face and ~5-15 N push force. The 45° bed-edge chamfers curled: no chamfers or rounds at the plate.
- gator-clip (pre-polish revision) test print: the one-piece compliant clip "worked excellently", and its 0.9 mm toe notches printed fine, so features of about 2 line widths are OK for silhouette detail (the critic predicted fuzz).
- movement 114 test print: snaps "quite nice, easy to assemble, sturdy"; the sliding frame (square rod in a hole printed axis-VERTICAL, flat-on-flat) "works very very well". But the crank axis has "a lot of slack", the gears "don't mesh super well", rotation isn't clean, and the crank works the front hub loose. Measured in the design's own sections: a tri-flat journal (73% of round) in a 45-deg-roof (teardrop) horizontal hole with 0.3 mm radial gap lifts 0.74-1.8 mm toward the roof depending on angle (tooth working depth is ~0.7-1.2), bobs 0.14 mm and shuffles +-0.22 mm sideways each turn; bearing L/D 0.96 with the pinion overhung 6.4 mm allows ~5.8 deg tilt. Rules: journals are ROUND wherever they run (flats only inside hubs); running bearings go in holes printed axis-vertical (teardrops are for clearance holes, not bearings); bearing length >= 1.5 D or two bearings straddling the load; kill axial play with thrust shoulders on both sides; check centre-distance swing against tooth depth before printing gears.

## build123d gotchas
- `a & b` returns `None` when the shapes don't intersect. Check before using `.volume`.
- `Plane.XZ * Polygon(...)` puts the polygon's (x, y) on world (x, z). Extrude with `both=True` for a symmetric width.
- Select edges by geometry, e.g. `shape.edges().group_by(Axis.Z)[0]` (bottom loop), or filter by `e.center()`. Use `Solid.chamfer(len, None, edges)` and `.fillet(r, edges)`.
- `RectangleRounded` radius must be < half the smaller side. Inner offsets use `r - wall`.

## forge studio
The user may be watching live (`forge studio`, port 8765; launch config `forge-studio`). It hot-reloads previews of design.py on save (`forge preview`, written to build/preview/ only) and plays motion sweeps from build/motion/poses.json. Journal decisions as you make them, so the feed is meaningful.

## Physics (MuJoCo) and plate view
- `forge physics <p> [--rpm N] [--scan]` infers joints, driver and contact pairs from the verified motion sweep (no extra design code) and simulates gravity, inertia and contact. Its headline metric is follower lift-off ("jump") versus crank speed, plus crank torque. It's validated against e·ω² = g (tests/test_physics.py). Numerics: dt 0.1 ms with a 2 ms contact; coarser steps chatter and fake early jumps. Don't cap hull vertices: faceted cams kick followers. `forge run` runs a speed scan for any design with `motion`.
- Bought hardware: `Part(..., purchased=True)` is included in fit, motion and physics, but not checked or sliced.
- Studio has Assembly / Plate / Physics modes. Live physics self-tests on start: if the crank can't turn through its own convex-hull contacts (gear and rack teeth jam), it switches to COUPLED mode, where follower joints are tied to the crank by the verified sweep's q(theta) with a 0.15 mm / 1 deg dead band of slack and the reaction torque goes on the crank. It's kinematic, labelled in the UI, and never a physics verdict. Frames stream at 60 Hz and are interpolated about 50 ms behind; the hand dial is a lead-compensated servo. Physics is LIVE (forge/live.py): MuJoCo runs in real time on the user's machine. The user drags a crank dial (hand), sets a motor speed, and grabs any moving part to poke it (spring drag). Chips show each follower on its cam or airborne, from the contact list. The plate view reads the slicer's real arrangement from the 3MF (forge/plate.py).

## Commands
```
make setup      # venv (python3.12) + deps + ccx
make test       # FEA validation + known-bad fixtures (every check must be able to fail)
.venv/bin/forge doctor
.venv/bin/forge run <project> [--fast]
```
