"""Rigid-body dynamics with MuJoCo, inferred from the verified motion sweep.

    forge physics <project> [--rpm 120] [--scan]

The motion sweep says where every part *should* be at each crank angle (kinematics).
This module asks what the parts actually *do* under gravity, inertia and contact:
  - do cam followers stay on their cams, or jump off at speed?
  - how much torque does the crank need?
No extra modelling from the designer: the model is inferred from the sweep's poses.
  1. Parts that move rigidly together become one body (a frog pressed on its rod).
  2. Each body is classified: static, hinge (axis + pivot fitted from the poses),
     slide (direction fitted), or complex (driven kinematically, i.e. prescribed).
  3. The driver is the hinge whose angle tracks the motion parameter (the crank).
  4. Contact pairs: moving bodies the sweep shows within 0.6 mm of each other.
     Collision shapes are convex decompositions (CoACD, cached per part hash).
  5. Guides (deck holes, bearings) are idealised by the joints themselves.
Validated: the follower-jump speed of an eccentric cam matches e·ω² = g (tests/test_physics.py).
Numerics: dt 0.1 ms with a 2 ms critically-damped contact. Coarser steps made the follower
chatter (a solver artifact that showed up as early 'jumps').
Honest limits: rigid bodies (no flex), estimated mass (solid density × fill factor),
generic PETG friction, idealised joints (no guide friction or slop)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from . import config
from .checks import check
from .config import ForgeError
from .project import Project

FILL_FACTOR = 0.55          # walls + 25% gyroid on small parts, as a fraction of solid density (estimate)
MU = 0.3                    # PETG on PETG, dry (estimate)
CONTACT_GAP_MM = 0.6
JUMP_MM = 0.3               # follower lift above its kinematic position that counts as losing contact
JUMP_DEG = 2.0
HAND_RPM = 120              # brisk hand cranking: 2 rev/s


def _poses(proj: Project, allow_stale: bool = False):
    f = proj.build_dir / "motion" / "poses.json"
    if not f.exists() or (proj.stale("fit") and not allow_stale):
        raise ForgeError(f"{proj.name}: needs a current motion sweep. Run `forge fit {proj.name}` (or `forge run`).")
    d = json.loads(f.read_text())
    names = list(d["poses"][0]["M"])
    T = np.array([p["t"] for p in d["poses"]])
    M = {n: np.array([np.array(p["M"][n]).reshape(4, 4) for p in d["poses"]]) for n in names}
    return d, T, M


def infer(T: np.ndarray, M: dict[str, np.ndarray]) -> dict:
    """Group parts into rigid bodies and classify each body's joint."""
    names = list(M)
    bodies: list[list[str]] = []
    for n in names:
        for b in bodies:
            r = b[0]
            rel = np.einsum("kij,kjl->kil", np.linalg.inv(M[r]), M[n])
            if np.allclose(rel, rel[0], atol=1e-4):
                b.append(n)
                break
        else:
            bodies.append([n])
    out = []
    for b in bodies:
        A = M[b[0]]
        rel = np.einsum("kij,jl->kil", A, np.linalg.inv(A[0]))  # world motion relative to pose 0
        rv = Rotation.from_matrix(rel[:, :3, :3]).as_rotvec()
        ang = np.linalg.norm(rv, axis=1)
        trans = rel[:, :3, 3]
        info = {"parts": b, "rep": b[0], "M0": A[0]}
        if ang.max() < 1e-4 and np.abs(trans).max() < 1e-4:
            info["kind"] = "static"
        elif ang.max() < 1e-4:
            U, S, Vt = np.linalg.svd(trans - trans.mean(axis=0))
            if S[1] < 1e-3 * max(S[0], 1e-9):
                u = Vt[0] if Vt[0][2] >= 0 else -Vt[0]  # point slides up (or +x if horizontal) so + means lift
                if abs(u[2]) < 1e-6 and u[0] < 0:
                    u = -u
                info.update(kind="slide", axis=u, q=trans @ u)
            else:
                info["kind"] = "complex"
        else:
            k = int(np.argmax(ang))
            axis = rv[k] / ang[k]
            ok = all(np.abs(np.dot(rv[i] / ang[i], axis)) > 0.999 for i in range(len(ang)) if ang[i] > 1e-3)
            # pivot: points p with R p + t = p for every pose  ->  (I - R) p = t, least squares
            Asys = np.concatenate([np.eye(3) - rel[i, :3, :3] for i in range(len(ang)) if ang[i] > 1e-3])
            bsys = np.concatenate([trans[i] for i in range(len(ang)) if ang[i] > 1e-3])
            p, *_ = np.linalg.lstsq(Asys, bsys, rcond=None)
            resid = np.linalg.norm(Asys @ p - bsys) / max(len(bsys), 1) ** 0.5
            if ok and resid < 0.05:
                signed = np.array([np.dot(rv[i], axis) for i in range(len(ang))])
                info.update(kind="hinge", axis=axis, anchor=p, q=np.unwrap(signed))
            else:
                info["kind"] = "complex"
        out.append(info)
    # driver: the hinge whose angle tracks the motion parameter one-to-one
    best, err = None, 1e9
    for info in out:
        if info["kind"] != "hinge":
            continue
        q = np.degrees(info["q"])
        for sgn in (1, -1):
            e = np.abs(sgn * q - (T - T[0])).max()
            if e < err:
                best, err, info["_sgn"] = info, e, sgn
    if best is None or err > 2.0:
        raise ForgeError("No body rotates one-to-one with the motion parameter, so there's no crank to drive.")
    best["kind"] = "driver"
    if best["_sgn"] < 0:
        best["axis"] = -best["axis"]
        best["q"] = -best["q"]
    return {"bodies": out, "driver": best["rep"]}


def _hulls(proj: Project, part: str, meta: dict) -> list[Path]:
    import trimesh
    cache = proj.build_dir / "physics" / "hulls"
    cache.mkdir(parents=True, exist_ok=True)
    tag = f"{part}_{meta['hash'][:10]}"
    found = sorted(cache.glob(f"{tag}_*.stl"))
    if found:
        return found
    for old in cache.glob(f"{part}_*.stl"):
        old.unlink()
    m = trimesh.load_mesh(proj.dir / meta["stl"])
    hull = m.convex_hull
    if m.volume > 0.92 * hull.volume:  # already convex enough
        pieces = [hull]
    else:
        import coacd
        coacd.set_log_level("error")
        res = coacd.run_coacd(coacd.Mesh(m.vertices, m.faces), threshold=0.06, max_convex_hull=10)
        pieces = [trimesh.Trimesh(v, f).convex_hull for v, f in res]
    out = []
    for i, p in enumerate(pieces):
        f = cache / f"{tag}_{i:02d}.stl"
        p.export(f)
        out.append(f)
    return out


def _quat(R):
    x, y, z, w = Rotation.from_matrix(R).as_quat()
    return f"{w:.8f} {x:.8f} {y:.8f} {z:.8f}"


def build_model(proj: Project, model: dict, pairs: list[tuple[str, str]], rpm: float) -> tuple[str, dict]:
    man = proj.manifest()
    mm = 1e-3
    assets, bodies_xml, contact_xml, part_geoms = [], [], [], {}
    collide_parts = {p for pr in pairs for p in pr}
    for info in model["bodies"]:
        if info["kind"] == "static":
            continue
        M0 = info["M0"]
        geoms = []
        for pn in info["parts"]:
            meta = man["parts"][pn]
            mat = config.material(meta["material"])
            rho = mat["density_g_cm3"] * 1000 * FILL_FACTOR
            Prel = np.linalg.inv(M0) @ model["part_M0"][pn]
            pos = " ".join(f"{v * mm:.8f}" for v in Prel[:3, 3])
            q = _quat(Prel[:3, :3])
            assets.append(f'<mesh name="m_{pn}" file="{proj.dir / meta["stl"]}" scale="{mm} {mm} {mm}" inertia="exact"/>')
            geoms.append(f'<geom name="v_{pn}" type="mesh" mesh="m_{pn}" pos="{pos}" quat="{q}" density="{rho:.1f}" '
                         f'contype="0" conaffinity="0" group="1"/>')
            if pn in collide_parts:
                names = []
                for i, h in enumerate(_hulls(proj, pn, meta)):
                    assets.append(f'<mesh name="h_{pn}_{i}" file="{h}" scale="{mm} {mm} {mm}"/>')
                    g = f"c_{pn}_{i}"
                    names.append(g)
                    geoms.append(f'<geom name="{g}" type="mesh" mesh="h_{pn}_{i}" pos="{pos}" quat="{q}" mass="0" '
                                 f'contype="0" conaffinity="0" group="2" friction="{MU} 0.005 0.0001" condim="3"/>')
                part_geoms[pn] = names
        pos0 = " ".join(f"{v * mm:.8f}" for v in M0[:3, 3])
        joint = ""
        if info["kind"] in ("hinge", "driver"):
            ax = M0[:3, :3].T @ info["axis"]
            anc = np.linalg.inv(M0) @ np.append(info["anchor"], 1)
            rng = ""
            if info["kind"] == "hinge":
                lo, hi = np.degrees(info["q"].min()) - 6, np.degrees(info["q"].max()) + 6
                rng = f'limited="true" range="{lo:.2f} {hi:.2f}"'
            joint = (f'<joint name="j_{info["rep"]}" type="hinge" axis="{ax[0]:.8f} {ax[1]:.8f} {ax[2]:.8f}" '
                     f'pos="{anc[0] * mm:.8f} {anc[1] * mm:.8f} {anc[2] * mm:.8f}" damping="{1e-5 if info["kind"] == "driver" else 2e-6}" {rng}/>')
        elif info["kind"] == "slide":
            ax = M0[:3, :3].T @ info["axis"]
            lo, hi = info["q"].min() - 2.0, info["q"].max() + 1.5  # stops: the guide/foot shoulder (estimate)
            joint = (f'<joint name="j_{info["rep"]}" type="slide" axis="{ax[0]:.8f} {ax[1]:.8f} {ax[2]:.8f}" '
                     f'damping="2e-4" limited="true" range="{lo * mm:.6f} {hi * mm:.6f}"/>')
        mocap = ' mocap="true"' if info["kind"] == "complex" else ""
        bodies_xml.append(f'<body name="b_{info["rep"]}" pos="{pos0}" quat="{_quat(M0[:3, :3])}"{mocap}>{joint}{"".join(geoms)}</body>')
    for a, b in pairs:
        for ga in part_geoms.get(a, []):
            for gb in part_geoms.get(b, []):
                contact_xml.append(f'<pair geom1="{ga}" geom2="{gb}" friction="{MU} {MU} 0.005 0.0001 0.0001" condim="3" solref="0.002 1" solimp="0.95 0.99 0.0005"/>')
    drv = model["driver"]
    xml = f"""<mujoco model="{proj.name}">
<compiler angle="degree" meshdir="/" autolimits="true"/>
<option timestep="0.0001" integrator="implicitfast" gravity="0 0 -9.81" cone="elliptic"/>
<asset>{''.join(assets)}</asset>
<worldbody>{''.join(bodies_xml)}</worldbody>
<contact>{''.join(contact_xml)}</contact>
<actuator><velocity name="crank" joint="j_{drv}" kv="0.05"/></actuator>
</mujoco>"""
    return xml, part_geoms


def simulate(proj: Project, rpm: float = HAND_RPM, revs: float = 2.0, fps: int = 60, record: bool = True) -> dict:
    import mujoco
    d, T, M = _poses(proj)
    model = infer(T, M)
    model["part_M0"] = {n: M[n][0] for n in M}
    fit = proj.result("fit") or {}
    kinds = {p: b["kind"] for b in model["bodies"] for p in b["parts"]}
    body_of = {p: b["rep"] for b in model["bodies"] for p in b["parts"]}
    pairs = []
    for c in fit.get("checks", []):
        if not c["id"].startswith("sweep:"):
            continue
        a, b = c["id"][6:].split("|")
        if body_of.get(a) == body_of.get(b):
            continue
        if "static" in (kinds.get(a), kinds.get(b)):
            continue  # guides are idealised by the joints
        if (c.get("value") or {}).get("min_gap_mm", 99) <= CONTACT_GAP_MM:
            pairs.append((a, b))
    xml, _ = build_model(proj, model, pairs, rpm)
    out_dir = proj.build_dir / "physics"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "model.xml").write_text(xml)
    m = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(m)
    jid = {b["rep"]: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, f"j_{b['rep']}") for b in model["bodies"]
           if b["kind"] in ("hinge", "slide", "driver")}
    bid = {b["rep"]: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"b_{b['rep']}") for b in model["bodies"] if b["kind"] != "static"}
    drv = model["driver"]
    omega = rpm / 60 * 2 * math.pi
    # settle under gravity, then spin up over 0.15 s and run
    settle, spin = 0.3, 0.15
    total = settle + spin + revs * 60 / rpm
    frames, devs, torque = [], {r: [] for r in jid if r != drv}, []
    qd = np.degrees
    drv_info = next(b for b in model["bodies"] if b["rep"] == drv)
    t_next = 0.0
    geom_body = np.array(m.geom_bodyid)
    follower_bid = {r: bid[r] for r in jid if r != drv}
    last_touch = {r: None for r in follower_bid}
    longest_air = {r: 0.0 for r in follower_bid}
    while data.time < total:
        t = data.time
        data.ctrl[0] = 0 if t < settle else omega * min(1.0, (t - settle) / spin)
        # complex bodies follow their swept trajectory against the crank angle (prescribed)
        ang = (qd(data.qpos[m.jnt_qposadr[jid[drv]]]) % 360) if drv in jid else 0
        for b in model["bodies"]:
            if b["kind"] == "complex":
                k = np.searchsorted(T - T[0], ang) % len(T)
                Mk = M[b["rep"]][k]
                mid = m.body_mocapid[bid[b["rep"]]]
                data.mocap_pos[mid] = Mk[:3, 3] * 1e-3
                x, y, z, w = Rotation.from_matrix(Mk[:3, :3]).as_quat()
                data.mocap_quat[mid] = [w, x, y, z]
        mujoco.mj_step(m, data)
        touching = set()
        for k_ in range(data.ncon):
            c = data.contact[k_]
            touching.add(int(geom_body[c.geom1]))
            touching.add(int(geom_body[c.geom2]))
        for r, b_ in follower_bid.items():
            if b_ in touching or last_touch[r] is None and t < settle + spin:
                last_touch[r] = t
            elif t >= settle + spin and last_touch[r] is not None:
                longest_air[r] = max(longest_air[r], t - last_touch[r])
        if t >= settle + spin:
            torque.append(abs(float(data.actuator_force[0])) * 1000)  # N·mm
            ca = qd(data.qpos[m.jnt_qposadr[jid[drv]]])
            for r, j in jid.items():
                if r == drv:
                    continue
                b = next(x for x in model["bodies"] if x["rep"] == r)
                kin = np.interp(ca % 360, T - T[0], b["q"], period=360)
                q = data.qpos[m.jnt_qposadr[j]]
                devs[r].append((q * 1000 - kin) if b["kind"] == "slide" else qd(q - kin))
        if record and t >= t_next:
            t_next += 1 / fps
            fr = {"t": round(t, 4)}
            for b in model["bodies"]:
                if b["kind"] == "static":
                    continue
                i = bid[b["rep"]]
                W = np.eye(4)
                W[:3, :3] = data.xmat[i].reshape(3, 3)
                W[:3, 3] = data.xpos[i] * 1000
                for pn in b["parts"]:
                    P = W @ (np.linalg.inv(b["M0"]) @ M[pn][0])
                    fr[pn] = [round(v, 5) for v in P.ravel()]
            frames.append(fr)
    metrics = {}
    for r, dv in devs.items():
        dv = np.array(dv)
        b = next(x for x in model["bodies"] if x["rep"] == r)
        thr = JUMP_MM if b["kind"] == "slide" else JUMP_DEG
        base = float(np.percentile(dv, 20))  # resting offset: designed gap + convex-hull approximation
        lift = dv - base
        air = longest_air.get(r, 0.0)
        metrics[r] = {"kind": b["kind"], "max_lift": round(float(lift.max()), 3), "baseline": round(base, 3),
                      "unit": "mm" if b["kind"] == "slide" else "deg", "longest_airborne_ms": round(1000 * air, 1),
                      "off_cam_pct": round(100 * float((lift > thr).mean()), 1),
                      "jumps": bool(air > 0.02)}  # verdict: lost all contact for > 20 ms (same signal as live mode)
    pair_bodies = {frozenset((body_of[a], body_of[b])) for a, b in pairs}

    def gravity_returned(b):
        # validated case: gravity pulls the follower back onto its driver
        if b["kind"] == "slide":
            return abs(float(b["axis"][2])) > 0.9          # near-vertical slide
        if b["kind"] == "hinge":
            return abs(float(b["axis"][2])) < 0.3          # horizontal hinge axis
        return False
    fbodies = {b["rep"]: b for b in model["bodies"]}
    validated = (not any(b["kind"] == "complex" for b in model["bodies"]) and bool(follower_bid)
                 and all(gravity_returned(fbodies[r]) for r in follower_bid)
                 and any(frozenset((r, drv)) in pair_bodies for r in follower_bid))
    # stall: if the driver didn't turn as commanded, the collision shapes jammed and nothing here is meaningful
    turned = abs(float(data.qpos[m.jnt_qposadr[jid[drv]]]))
    commanded = omega * (total - settle - spin / 2)
    stalled = turned < 0.9 * commanded
    res = {"rpm": rpm, "metrics": metrics, "validated": validated, "stalled": bool(stalled),
           "turned_deg": round(float(np.degrees(turned)), 1), "commanded_deg": round(float(np.degrees(commanded)), 1), "torque_peak_nmm": round(max(torque), 2) if torque else 0,
           "torque_rms_nmm": round(float(np.sqrt(np.mean(np.square(torque)))), 2) if torque else 0,
           "bodies": [{"rep": b["rep"], "parts": b["parts"], "kind": b["kind"]} for b in model["bodies"]],
           "pairs": pairs, "frames": frames if record else []}
    return res


def scan(proj: Project, rpms=(30, 60, 120, 240, 360, 480, 600, 720)) -> dict:
    rows = []
    for r in rpms:
        s = simulate(proj, rpm=r, revs=2.0, record=False)
        rows.append({"rpm": r, "jumps": [k for k, v in s["metrics"].items() if v["jumps"]],
                     "max_lift": {k: v["max_lift"] for k, v in s["metrics"].items()}, "torque_peak_nmm": s["torque_peak_nmm"]})
    jump_rpm = next((row["rpm"] for row in rows if row["jumps"]), None)
    hand = next((row for row in rows if row["rpm"] == HAND_RPM), rows[-1])
    probe = simulate(proj, rpm=HAND_RPM, revs=0.5, record=False)
    if probe["stalled"]:
        return {"scan": rows, "jump_rpm": None, "validated": False, "stalled": True,
                "checks": [check("physics:contact", "Mechanism dynamics", "warn", "estimated", value=probe["turned_deg"],
                                 limit=probe["commanded_deg"],
                                 detail="The simulated drive STALLED: the convex collision shapes jam where the real parts "
                                        "don't (typical for gear teeth). These physics results are invalid; don't use them.")],
                "assumptions": ["Physics invalid: driver stalled."]}
    validated = probe["validated"]
    if not validated:
        return {"scan": rows, "jump_rpm": jump_rpm, "validated": False,
                "checks": [check("physics:contact", "Mechanism dynamics", "info", "estimated", value=None,
                                 detail="Not validated for this mechanism type. forge's physics is validated for cam followers "
                                        "returned by gravity. Gears, ratchets and prescribed bodies need a human or a dedicated test. "
                                        "Use live mode in studio to explore, not as evidence.")],
                "assumptions": ["Physics shown for exploration only."]}
    checks = [check("physics:contact", "Followers stay on their cams", "pass" if not hand["jumps"] else "warn", "estimated",
                    value={"first_jump_rpm": jump_rpm, "at_hand_rpm": hand["jumps"] or "none"}, limit={"hand_rpm": HAND_RPM},
                    detail=f"MuJoCo, gravity-returned followers. The first crank speed where a follower lifts > {JUMP_MM} mm "
                           f"off its kinematic path: {jump_rpm or 'none up to ' + str(rpms[-1])} rpm."),
              check("physics:torque", "Crank effort", "info", "estimated", value=hand["torque_peak_nmm"],
                    detail=f"Peak crank torque at {HAND_RPM} rpm (N·mm), friction μ={MU}, rigid parts.")]
    return {"scan": rows, "jump_rpm": jump_rpm, "checks": checks,
            "assumptions": [f"Rigid bodies; mass = solid density × {FILL_FACTOR} fill factor (estimate).",
                            f"PETG-on-PETG friction μ = {MU} (estimate); guides idealised as frictionless joints.",
                            "Joints and contact pairs are inferred from the verified motion sweep.",
                            "Slide stops: 1.5 mm above the swept top (estimate of the guide shoulder)."]}


def run(proj: Project, rpm: float = HAND_RPM, do_scan: bool = True) -> dict:
    s = simulate(proj, rpm=rpm)
    (proj.build_dir / "physics" / f"traj_{int(rpm)}.json").write_text(json.dumps(s))
    r = {"status": "pass", "rpm": rpm, "metrics": s["metrics"], "torque_peak_nmm": s["torque_peak_nmm"],
         "bodies": s["bodies"], "pairs": s["pairs"]}
    if do_scan:
        sc = scan(proj)
        r.update(sc)
        r["status"] = "warn" if any(c["status"] == "warn" for c in sc["checks"]) else "pass"
    proj.save("physics", r)
    return r
