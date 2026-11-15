"""Live, interactive MuJoCo for forge studio.

One LiveSim per project runs in a background thread, as close to real time as the model
allows. Studio streams poses over SSE and sends controls:
  {"mode": "speed", "rpm": 120}      motor: hold this crank speed
  {"mode": "angle", "deg": 37.5}     hand: follow a dragged crank angle (unwrapped, degrees)
  {"poke": {"part", "point", "target"}} spring-drag a part (world mm); {"poke": null} releases
  {"reset": true}
The model is the same one `forge physics` infers from the verified motion sweep.

Two drive modes, chosen by a short self-test when the sim starts:
  contact  followers are driven through convex-hull contacts (cams, followers, gravity return).
           This is the validated case (forge physics: e*w^2 = g).
  coupled  convex hulls jam on gear and rack teeth, so if the crank can't turn through its own
           contacts the follower joints are tied to the crank by the verified sweep's q(theta)
           table instead: a stiff spring with a dead band (the joint's slack), with the equal and
           opposite torque on the crank. It is kinematic, labelled as such, never a verdict.
"""
from __future__ import annotations

import math
import threading
import time

import numpy as np

from . import physics
from .project import Project

MAX_RPM = 900
SELFTEST_RPM = 30.0
SELFTEST_S = 0.6           # sim seconds of the contact self-test
SELFTEST_MIN = 0.7         # fraction of the commanded rotation the crank must reach
SLACK_MM = 0.15            # coupled dead band on slides (per side): a typical sliding gap
SLACK_DEG = 1.0            # coupled dead band on hinges (per side)
COUPLE_HZ = 25.0           # coupling spring natural frequency
POKE_HZ = 12.0             # poke spring natural frequency


class LiveSim:
    def __init__(self, name: str):
        import mujoco
        self.mj = mujoco
        self.name = name
        proj = Project(name)
        d, T, M = physics._poses(proj, allow_stale=True)  # play is allowed on the last sweep; studio shows if it's stale
        self.stale = proj.stale("fit")
        model = physics.infer(T, M)
        model["part_M0"] = {n: M[n][0] for n in M}
        fit = proj.result("fit") or {}
        kinds = {p: b["kind"] for b in model["bodies"] for p in b["parts"]}
        body_of = {p: b["rep"] for b in model["bodies"] for p in b["parts"]}
        pairs = []
        for c in fit.get("checks", []):
            if c["id"].startswith("sweep:"):
                a, b = c["id"][6:].split("|")
                if body_of.get(a) != body_of.get(b) and "static" not in (kinds.get(a), kinds.get(b)) \
                        and (c.get("value") or {}).get("min_gap_mm", 99) <= physics.CONTACT_GAP_MM:
                    pairs.append((a, b))
        self.model, self.T, self.M = model, T, M
        self.build_hash = proj.manifest()["build_hash"]
        self.drv = model["driver"]
        self.part_body = {p: b["rep"] for b in model["bodies"] if b["kind"] != "static" for p in b["parts"]}
        self.static_parts = [p for b in model["bodies"] if b["kind"] == "static" for p in b["parts"]]
        self.offset = {p: np.linalg.inv(b["M0"]) @ M[p][0] for b in model["bodies"] for p in b["parts"]}
        self.followers = [b["rep"] for b in model["bodies"] if b["kind"] in ("slide", "hinge")]
        self.complex = [b["rep"] for b in model["bodies"] if b["kind"] == "complex"]
        self._tables(model)

        self._load(physics.build_model(proj, model, pairs, 120)[0])
        self.mode = "contact"
        self.selftest = None
        if self.followers and pairs:
            frac = self._selftest()
            self.selftest = round(frac, 2)
            if frac < SELFTEST_MIN:
                # the crank can't turn through its own contacts (tooth hulls jam): couple from the sweep
                self._load(physics.build_model(proj, model, [], 120)[0])
                self.m.opt.timestep = 0.001   # no contacts left to resolve
                self.mode = "coupled"
        elif self.followers:
            self.mode = "coupled"
        self._gains()

        self.last_touch = {r: 0.0 for r in self.followers}
        self.ctrl = {"mode": "speed", "rpm": 0.0, "deg": 0.0, "rate": 0.0, "at": time.time()}
        self.poke = None
        self.lock = threading.Lock()
        self.frame = None
        self.version = 0
        self.speed_factor = 1.0
        self.last_seen = time.time()
        self.alive = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    # ---------------- model ----------------
    def _load(self, xml: str):
        mj = self.mj
        self.m = mj.MjModel.from_xml_string(xml)
        self.d = mj.MjData(self.m)
        jn = lambda r: mj.mj_name2id(self.m, mj.mjtObj.mjOBJ_JOINT, f"j_{r}")
        bn = lambda r: mj.mj_name2id(self.m, mj.mjtObj.mjOBJ_BODY, f"b_{r}")
        self.jdrv = jn(self.drv)
        self.drv_q = self.m.jnt_qposadr[self.jdrv]
        self.drv_v = self.m.jnt_dofadr[self.jdrv]
        self.bid = {b["rep"]: bn(b["rep"]) for b in self.model["bodies"] if b["kind"] != "static"}
        self.fj = {r: (self.m.jnt_qposadr[jn(r)], self.m.jnt_dofadr[jn(r)]) for r in self.followers}
        self.geom_body = np.array(self.m.geom_bodyid)

    def _tables(self, model):
        """q(theta) for every follower from the verified sweep. theta = crank joint angle (deg) from pose 0."""
        drv = next(b for b in model["bodies"] if b["rep"] == model["driver"])
        x = np.degrees(np.asarray(drv["q"], float) - drv["q"][0])
        self.sign = 1.0 if x[-1] >= 0 else -1.0
        x = x * self.sign
        step = float(np.median(np.diff(x))) if len(x) > 1 else 360.0
        self.period = float(x[-1] + step)
        self.tab_x = np.append(x, self.period)
        self.tab = {}
        for b in model["bodies"]:
            if b["kind"] in ("slide", "hinge"):
                q = np.asarray(b["q"], float) - b["q"][0]
                q = q * 1e-3 if b["kind"] == "slide" else q          # model units: m, rad
                self.tab[b["rep"]] = (b["kind"], np.append(q, q[0]))
        self.cplx_k = lambda th: int(np.searchsorted(self.tab_x[:-1], th % self.period, side="right") - 1) % len(self.T)

    def _target(self, r, th_deg):
        kind, q = self.tab[r]
        u = (self.sign * th_deg) % self.period
        y = float(np.interp(u, self.tab_x, q))
        dy = (float(np.interp(u + 0.5, self.tab_x, q)) - float(np.interp(u - 0.5, self.tab_x, q))) if 0.5 <= u <= self.period - 0.5 else 0.0
        slope = dy / math.radians(1.0) * self.sign     # dq/dtheta per rad of crank
        return y, slope

    def _gains(self):
        mj = self.mj
        mj.mj_forward(self.m, self.d)
        w = 2 * math.pi * COUPLE_HZ
        self.k, self.c, self.band = {}, {}, {}
        for r, (qa, va) in self.fj.items():
            inert = 1.0 / max(float(self.m.dof_invweight0[va]), 1e-9)   # effective inertia at the reference pose
            self.k[r] = inert * w * w
            self.c[r] = 2 * 0.8 * inert * w
            self.band[r] = SLACK_MM * 1e-3 if self.tab[r][0] == "slide" else math.radians(SLACK_DEG)

    def _selftest(self) -> float:
        """Spin the crank through its contacts on a scratch copy; return the fraction of the commanded turn reached."""
        mj, m = self.mj, self.m
        d = mj.MjData(m)
        w = SELFTEST_RPM / 60 * 2 * math.pi
        n = int(SELFTEST_S / m.opt.timestep)
        for i in range(n):
            d.ctrl[0] = w * min(1.0, i / (0.2 * n))
            self._mocap(d)
            mj.mj_step(m, d)
        ideal = w * SELFTEST_S * 0.9                      # ramp over the first 20%
        return abs(d.qpos[self.drv_q]) / ideal

    def _mocap(self, d):
        if not self.complex:
            return
        from scipy.spatial.transform import Rotation
        k = self.cplx_k(self.sign * math.degrees(d.qpos[self.drv_q]))
        for r in self.complex:
            Mk = self.M[r][k]
            mid = self.m.body_mocapid[self.bid[r]]
            d.mocap_pos[mid] = Mk[:3, 3] * 1e-3
            x, y, z, w_ = Rotation.from_matrix(Mk[:3, :3]).as_quat()
            d.mocap_quat[mid] = [w_, x, y, z]

    # ---------------- control ----------------
    def control(self, msg: dict):
        with self.lock:
            if msg.get("reset"):
                self.mj.mj_resetData(self.m, self.d)
                self.ctrl = {"mode": "speed", "rpm": 0.0, "deg": 0.0, "rate": 0.0, "at": time.time()}
                self.poke = None
            if "mode" in msg:
                now = time.time()
                if msg["mode"] == "angle" and "deg" in msg:
                    # hand: estimate the hand's speed so the servo can lead instead of lag
                    if self.ctrl["mode"] == "angle" and now - self.ctrl["at"] < 0.25:
                        inst = (float(msg["deg"]) - self.ctrl["deg"]) / max(now - self.ctrl["at"], 1e-3)
                        self.ctrl["rate"] = 0.5 * self.ctrl["rate"] + 0.5 * inst
                    else:
                        self.ctrl["rate"] = 0.0
                    if msg.get("release"):
                        self.ctrl["rate"] = 0.0
                    self.ctrl["at"] = now
                self.ctrl["mode"] = msg["mode"]
                if "rpm" in msg:
                    self.ctrl["rpm"] = float(np.clip(msg["rpm"], -MAX_RPM, MAX_RPM))
                if "deg" in msg:
                    self.ctrl["deg"] = float(msg["deg"])
            if "poke" in msg:
                p = msg["poke"]
                if not p or p.get("part") not in self.part_body:
                    self.poke = None
                else:
                    r = self.part_body[p["part"]]
                    i = self.bid[r]
                    R = self.d.xmat[i].reshape(3, 3)
                    world = np.asarray(p["point"], float) * 1e-3
                    local = R.T @ (world - self.d.xpos[i]) if self.poke is None or self.poke.get("body") != i else self.poke["local"]
                    self.poke = {"body": i, "local": local, "target": np.asarray(p["target"], float) * 1e-3}

    # ---------------- loop ----------------
    def _crank_angle(self):
        return math.degrees(self.d.qpos[self.drv_q])

    def _hand_target(self):
        c = self.ctrl
        lead = min(time.time() - c["at"], 0.06)            # extrapolate between hand messages, at most 60 ms
        return c["deg"] + c["rate"] * lead, c["rate"]

    def _run(self):
        mj, m, d = self.mj, self.m, self.d
        frame_every = 1 / 60
        next_frame = 0.0
        wall0, sim0 = time.time(), 0.0
        wmax = MAX_RPM / 60 * 2 * math.pi
        while self.alive:
            if time.time() - self.last_seen > 45:  # nobody watching: stop
                self.alive = False
                break
            # step up to ~1/60 s of sim time per batch, then pace against the wall clock
            batch_end = d.time + 1 / 60
            while d.time < batch_end:
                with self.lock:
                    c = self.ctrl
                    if c["mode"] == "angle":
                        tgt, rate = self._hand_target()
                        err = math.radians(tgt - self._crank_angle())
                        d.ctrl[0] = float(np.clip(math.radians(rate) + 40 * err, -wmax, wmax))
                    else:
                        d.ctrl[0] = c["rpm"] / 60 * 2 * math.pi
                    d.qfrc_applied[:] = 0
                    if self.mode == "coupled":
                        th = self._crank_angle()
                        wd = d.qvel[self.drv_v]
                        for r, (qa, va) in self.fj.items():
                            y, slope = self._target(r, th)
                            e = y - d.qpos[qa]
                            b = self.band[r]
                            if abs(e) <= b:
                                continue                    # inside the slack: free (gravity, pokes)
                            e -= math.copysign(b, e)
                            F = self.k[r] * e + self.c[r] * (slope * wd - d.qvel[va])
                            d.qfrc_applied[va] += F
                            d.qfrc_applied[self.drv_v] -= F * slope
                    self._mocap(d)
                    if self.poke:
                        i = self.poke["body"]
                        R = d.xmat[i].reshape(3, 3)
                        pt = d.xpos[i] + R @ self.poke["local"]
                        mass = max(float(m.body_subtreemass[i]), 1e-4)
                        k = mass * (2 * math.pi * POKE_HZ) ** 2
                        vel = np.zeros(6)
                        mj.mj_objectVelocity(m, d, mj.mjtObj.mjOBJ_BODY, i, vel, 0)
                        F = k * (self.poke["target"] - pt) - 2 * math.sqrt(k * mass) * vel[3:]
                        mj.mj_applyFT(m, d, F, np.zeros(3), pt, i, d.qfrc_applied)
                    mj.mj_step(m, d)
                    if self.mode == "contact":
                        for k_ in range(d.ncon):
                            con = d.contact[k_]
                            b1, b2 = self.geom_body[con.geom1], self.geom_body[con.geom2]
                            for r in self.followers:
                                if self.bid[r] in (b1, b2):
                                    self.last_touch[r] = d.time
            if d.time >= next_frame:
                next_frame = d.time + frame_every
                self._snapshot()
            # pace to real time (if the model is slower than real time, just run flat out)
            ahead = (d.time - sim0) - (time.time() - wall0)
            if ahead > 0:
                time.sleep(min(ahead, 0.05))
            el = time.time() - wall0
            if el > 0.5:                 # speed estimate over at least half a second
                self.speed_factor = 0.7 * self.speed_factor + 0.3 * (d.time - sim0) / el
                wall0, sim0 = time.time(), d.time

    def _snapshot(self):
        d = self.d
        fr = {"t": round(d.time, 4), "M": {}}
        for r, i in self.bid.items():
            W = np.eye(4)
            W[:3, :3] = d.xmat[i].reshape(3, 3)
            W[:3, 3] = d.xpos[i] * 1000
            for p in [p for p, b in self.part_body.items() if b == r]:
                fr["M"][p] = [round(v, 4) for v in (W @ self.offset[p]).ravel()]
        rpm = d.qvel[self.drv_v] * 60 / (2 * math.pi)
        fr["rpm"] = round(float(rpm), 1)
        fr["angle"] = round(self._crank_angle(), 1)
        fr["torque_nmm"] = round(float(d.actuator_force[0]) * 1000, 2)
        if self.mode == "contact":
            fr["airborne"] = {r: (d.time - self.last_touch[r]) > 0.02 for r in self.followers}
        else:
            fr["airborne"] = {r: False for r in self.followers}
        fr["mode"] = self.mode
        fr["realtime"] = round(self.speed_factor, 2)
        fr["poking"] = self.poke is not None
        with self.lock:
            self.frame = fr
            self.version += 1


_SIMS: dict[str, LiveSim] = {}
_SIMS_LOCK = threading.Lock()


def get(name: str) -> LiveSim:
    with _SIMS_LOCK:
        s = _SIMS.get(name)
        try:
            bh = Project(name).manifest()["build_hash"]
        except Exception:
            bh = None
        if s is None or not s.alive or s.build_hash != bh:
            if s:
                s.alive = False
            s = LiveSim(name)
            _SIMS[name] = s
        s.last_seen = time.time()
        return s
