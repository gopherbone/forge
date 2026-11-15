"""Live, interactive MuJoCo for forge studio.

One LiveSim per project runs in a background thread, as close to real time as the model
allows. Studio streams poses over SSE and sends controls:
  {"mode": "speed", "rpm": 120}      motor: hold this crank speed
  {"mode": "angle", "deg": 37.5}     hand: follow a dragged crank angle (unwrapped, degrees)
  {"poke": {"part", "point", "target"}} spring-drag a part (world mm); {"poke": null} releases
  {"reset": true}
The model is the same one `forge physics` infers from the verified motion sweep."""
from __future__ import annotations

import math
import threading
import time

import numpy as np

from . import physics
from .project import Project

MAX_RPM = 900


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
        xml, part_geoms = physics.build_model(proj, model, pairs, 120)
        self.m = mujoco.MjModel.from_xml_string(xml)
        self.d = mujoco.MjData(self.m)
        self.model, self.T, self.M = model, T, M
        self.build_hash = proj.manifest()["build_hash"]
        self.drv = model["driver"]
        jn = lambda r: mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_JOINT, f"j_{r}")
        bn = lambda r: mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, f"b_{r}")
        self.jdrv = jn(self.drv)
        self.bid = {b["rep"]: bn(b["rep"]) for b in model["bodies"] if b["kind"] != "static"}
        self.part_body = {p: b["rep"] for b in model["bodies"] if b["kind"] != "static" for p in b["parts"]}
        self.static_parts = [p for b in model["bodies"] if b["kind"] == "static" for p in b["parts"]]
        self.offset = {p: np.linalg.inv(b["M0"]) @ M[p][0] for b in model["bodies"] for p in b["parts"]}
        # which geoms belong to which body, for "on cam / airborne" from the contact list
        self.geom_body = np.array(self.m.geom_bodyid)
        self.followers = [b["rep"] for b in model["bodies"] if b["kind"] in ("slide", "hinge")]
        self.last_touch = {r: 0.0 for r in self.followers}
        self.ctrl = {"mode": "speed", "rpm": 0.0, "deg": 0.0}
        self.poke = None
        self.lock = threading.Lock()
        self.frame = None
        self.version = 0
        self.speed_factor = 1.0
        self.last_seen = time.time()
        self.alive = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    # ---------------- control ----------------
    def control(self, msg: dict):
        with self.lock:
            if msg.get("reset"):
                self.mj.mj_resetData(self.m, self.d)
                self.ctrl = {"mode": "speed", "rpm": 0.0, "deg": 0.0}
                self.poke = None
            if "mode" in msg:
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
        return math.degrees(self.d.qpos[self.m.jnt_qposadr[self.jdrv]])

    def _run(self):
        mj, m, d = self.mj, self.m, self.d
        dt = m.opt.timestep
        frame_every = 1 / 40
        next_frame = 0.0
        wall0, sim0 = time.time(), 0.0
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
                        err = math.radians(c["deg"] - self._crank_angle())
                        d.ctrl[0] = float(np.clip(25 * err, -MAX_RPM / 60 * 2 * math.pi, MAX_RPM / 60 * 2 * math.pi))
                    else:
                        d.ctrl[0] = c["rpm"] / 60 * 2 * math.pi
                    d.qfrc_applied[:] = 0
                    if self.poke:
                        i = self.poke["body"]
                        R = d.xmat[i].reshape(3, 3)
                        pt = d.xpos[i] + R @ self.poke["local"]
                        mass = max(float(m.body_subtreemass[i]), 1e-4)
                        k = mass * 900.0
                        vel = np.zeros(6)
                        mj.mj_objectVelocity(m, d, mj.mjtObj.mjOBJ_BODY, i, vel, 0)
                        F = k * (self.poke["target"] - pt) - 2 * math.sqrt(k * mass) * vel[3:]
                        mj.mj_applyFT(m, d, F, np.zeros(3), pt, i, d.qfrc_applied)
                    mj.mj_step(m, d)
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
            self.speed_factor = (d.time - sim0) / max(time.time() - wall0, 1e-6)
            if ahead > 0:
                time.sleep(min(ahead, 0.05))
            if time.time() - wall0 > 5:  # rolling window for the speed estimate
                wall0, sim0 = time.time(), d.time

    def _snapshot(self):
        d = self.d
        fr = {"t": round(d.time, 3), "M": {}}
        for r, i in self.bid.items():
            W = np.eye(4)
            W[:3, :3] = d.xmat[i].reshape(3, 3)
            W[:3, 3] = d.xpos[i] * 1000
            for p in [p for p, b in self.part_body.items() if b == r]:
                fr["M"][p] = [round(v, 4) for v in (W @ self.offset[p]).ravel()]
        rpm = d.qvel[self.m.jnt_dofadr[self.jdrv]] * 60 / (2 * math.pi)
        fr["rpm"] = round(float(rpm), 1)
        fr["angle"] = round(self._crank_angle(), 1)
        fr["torque_nmm"] = round(float(d.actuator_force[0]) * 1000, 2)
        fr["airborne"] = {r: (d.time - self.last_touch[r]) > 0.02 for r in self.followers}
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
