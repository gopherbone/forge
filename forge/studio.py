"""forge studio: a live dashboard for watching agents work.

    forge studio [--port 8765]

- Hot reload: when an agent saves design.py or spec.yaml, studio runs an isolated
  geometry preview (forge preview) and swaps the model in, before any verification.
  If the design is mid-edit and throws, the error is shown instead.
- Verified state: pipeline stages, check issues, renders and journal from the agent's
  real builds, updated live (Server-Sent Events from a file-mtime watcher).
- Inspect: parts list, click-to-isolate (in the list or the 3D view), ghosting,
  explode slider, per-part info and issues.
- Motion: playback of the motion sweep's per-pose transforms with a scrubber.
The server binds 127.0.0.1, is read-only except for build/preview/, and is stdlib-only;
the page (forge/templates/studio.html) loads three.js from a CDN."""
from __future__ import annotations

import json
import mimetypes
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import config
from .project import Project

WATCH_GLOBS = ["spec.yaml", "design.py", "journal.md", "build/manifest.json", "build/results/*.json",
               "build/renders/*.png", "build/renders/*.gif", "build/preview/preview.json", "build/motion/poses.json"]
SOURCE = ("spec.yaml", "design.py")
TEMPLATE = Path(__file__).parent / "templates" / "studio.html"


def _projects() -> list[str]:
    return sorted(p.parent.name for p in config.PROJECTS.glob("*/spec.yaml") if not p.parent.name.startswith("_"))


def _fingerprint(name: str) -> dict[str, float]:
    d = config.PROJECTS / name
    out = {}
    for g in WATCH_GLOBS:
        for f in d.glob(g):
            try:
                out[str(f.relative_to(d))] = f.stat().st_mtime
            except FileNotFoundError:
                pass
    return out


def _journal(proj: Project, n: int = 80) -> list[dict]:
    p = proj.dir / "journal.md"
    if not p.exists():
        return []
    items = []
    for ln in p.read_text().splitlines():
        m = re.match(r"^- \*\*(.+?)\*\* (\S+) `(.+?)` — (.*)$", ln)
        if m:
            t, icon, who, text = m.groups()
            items.append({"at": t, "icon": icon, "who": who, "text": text})
    return items[-n:][::-1]


def _read_json(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def project_state(name: str) -> dict:
    proj = Project(name)
    spec = proj.spec or {}
    fp = _fingerprint(name)
    out = {"name": name, "title": spec.get("title", name), "journal": _journal(proj), "stages": {}, "parts": [],
           "issues": [], "renders": [], "kpis": {}, "last_change": max(fp.values()) if fp else 0, "source": "none"}
    src_mtime = max((fp.get(s, 0) for s in SOURCE), default=0)
    m = _read_json(proj.build_dir / "manifest.json")
    pv = _read_json(proj.build_dir / "preview" / "preview.json")
    man_t = fp.get("build/manifest.json", 0)
    pv_t = fp.get("build/preview/preview.json", 0)
    out["preview"] = ({"at": pv.get("at"), "error": pv.get("error"), "seconds": pv.get("seconds"),
                       "pending": src_mtime > max(pv_t, man_t)} if pv else {"pending": src_mtime > man_t, "error": None})
    # the preview only wins when it shows source the verified build hasn't seen yet
    use_preview = bool(pv and pv.get("parts") and (not m or (pv_t > man_t and pv.get("source_hash") != m.get("source_hash"))))
    if use_preview:
        out["source"] = "preview"
        for p in pv["parts"]:
            f = proj.dir / p["stl"]
            out["parts"].append({**p, "v": int((f.stat().st_mtime if f.exists() else 0) * 1000)})
    elif m:
        out["source"] = "build"
        for pn, v in m["parts"].items():
            f = proj.dir / v["stl"]
            out["parts"].append({"name": pn, "color": v.get("color"), "stl": v["stl"], "M": sum(v["placement_matrix"], []),
                                 "bbox": v["bbox_mm"], "volume": round(v["volume_mm3"] / 1000, 3), "material": v["material"],
                                 "notes": v.get("notes", ""), "v": int((f.stat().st_mtime if f.exists() else 0) * 1000)})
    if m:
        out["build_hash"] = m["build_hash"][:10]
        try:
            out["source_current"] = proj.source_hash() == m["source_hash"]
        except Exception:
            out["source_current"] = False
        for st in ["build", "orient", "check", "fit", "sim", "physics", "slice", "render", "report"]:
            r = proj.result(st)
            out["stages"][st] = {"status": (r or {}).get("status", "none"), "stale": proj.stale(st) if r else "not run"}
        chk = proj.result("check") or {}
        for pn, pr in (chk.get("parts") or {}).items():
            for c in pr["checks"]:
                if c["status"] in ("warn", "fail"):
                    out["issues"].append({"part": pn, "name": c["name"], "status": c["status"], "detail": c.get("detail", "")})
        for st in ("fit", "sim", "slice"):
            r = proj.result(st) or {}
            for case in r.get("cases", []):
                for c in case.get("checks", []):
                    if c["status"] in ("warn", "fail"):
                        out["issues"].append({"part": case.get("part", st), "name": c["name"], "status": c["status"],
                                              "detail": c.get("detail", "")})
            for c in r.get("checks", []):
                if c["status"] in ("warn", "fail"):
                    out["issues"].append({"part": "assembly", "name": c["name"], "status": c["status"], "detail": c.get("detail", "")})
            for pn, pr in (r.get("parts") or {}).items():
                for c in pr.get("checks", []):
                    if c["status"] in ("warn", "fail"):
                        out["issues"].append({"part": pn, "name": c["name"], "status": c["status"], "detail": c.get("detail", "")})
        sl = (proj.result("slice") or {}).get("totals")
        if sl:
            out["kpis"] = {"print": f"{int(sl['time_s'] // 3600)}h {int(sl['time_s'] % 3600 // 60):02d}m",
                           "filament": f"{sl['filament_g']:.0f} g", "support": f"{sl['support_g']:.1f} g"}
    for f in sorted((proj.build_dir / "renders").glob("*")):
        if f.suffix in (".png", ".gif"):
            out["renders"].append({"name": f.stem, "path": str(f.relative_to(proj.dir)), "v": int(f.stat().st_mtime)})
    order = {"motion": 0, "hero": 1, "section": 2, "exploded": 3}
    out["renders"].sort(key=lambda r: (order.get(r["name"], 9), r["name"]))
    return out


_PHYS_LOCK = threading.Lock()


def _physics(name: str, rpm: float) -> dict:
    """Run (or reuse) a MuJoCo sim at this crank speed for the current verified build."""
    from . import physics
    proj = Project(name)
    try:
        bh = proj.manifest()["build_hash"][:10]
    except Exception:
        return {"error": "Not built yet."}
    cache = proj.build_dir / "physics" / f"studio_{bh}_{int(rpm)}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    with _PHYS_LOCK:
        try:
            s = physics.simulate(proj, rpm=rpm, revs=2.0, fps=60)
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}
    scan = (proj.result("physics") or {}) if not proj.stale("physics") else {}
    out = {"rpm": rpm, "frames": s["frames"], "metrics": s["metrics"], "torque_peak_nmm": s["torque_peak_nmm"],
           "bodies": s["bodies"], "jump_rpm": scan.get("jump_rpm"), "scan": scan.get("scan", [])}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out))
    return out


class Previewer(threading.Thread):
    """Debounced, one-at-a-time preview builds when an agent saves design.py / spec.yaml."""
    daemon = True

    def __init__(self):
        super().__init__()
        self.queue: dict[str, float] = {}
        self.lock = threading.Lock()

    def request(self, name: str):
        with self.lock:
            self.queue[name] = time.time()

    def run(self):
        while True:
            time.sleep(0.4)
            with self.lock:
                due = [n for n, t in self.queue.items() if time.time() - t > 1.2]  # debounce bursts of saves
                for n in due:
                    self.queue.pop(n)
            for n in due:
                try:
                    subprocess.run([sys.executable, "-m", "forge.cli", "preview", n], cwd=config.ROOT,
                                   capture_output=True, timeout=180)
                except Exception:
                    pass


class Watcher(threading.Thread):
    daemon = True

    def __init__(self, previewer: Previewer):
        super().__init__()
        self.version = 0
        self.changed: dict[str, float] = {}
        self.cond = threading.Condition()
        self.previewer = previewer
        self._prev: dict[str, dict] = {}

    def run(self):
        first = True
        while True:
            now = {n: _fingerprint(n) for n in _projects()}
            for n, fp in now.items():
                if "design.py" not in fp:
                    continue
                old = self._prev.get(n, {})
                src_changed = any(fp.get(s) != old.get(s) for s in SOURCE)
                behind = max(fp.get(s, 0) for s in SOURCE) > max(fp.get("build/preview/preview.json", 0),
                                                                fp.get("build/manifest.json", 0))
                if (src_changed and not first) or (first and behind):
                    self.previewer.request(n)
            diff = [n for n in now if now[n] != self._prev.get(n)] + [n for n in self._prev if n not in now]
            if diff and not first:
                with self.cond:
                    self.version += 1
                    for n in diff:
                        self.changed[n] = time.time()
                    self.cond.notify_all()
            self._prev, first = now, False
            time.sleep(0.6)


PREVIEWER = Previewer()
WATCHER = Watcher(PREVIEWER)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        self._send(200, json.dumps(obj, default=str).encode(), "application/json")

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/":
            return self._send(200, TEMPLATE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/projects":
            out = []
            for n in _projects():
                fp = _fingerprint(n)
                pv = _read_json(config.PROJECTS / n / "build" / "preview" / "preview.json") or {}
                out.append({"name": n, "title": (Project(n).spec or {}).get("title", n),
                            "last_change": max(fp.values() or [0]), "error": bool(pv.get("error"))})
            return self._json(out)
        m = re.match(r"^/api/project/([\w.-]+)$", path)
        if m and m.group(1) in _projects():
            return self._json(project_state(m.group(1)))
        m = re.match(r"^/api/motion/([\w.-]+)$", path)
        if m and m.group(1) in _projects():
            proj = Project(m.group(1))
            d = _read_json(proj.build_dir / "motion" / "poses.json") or {"poses": []}
            d["stale"] = proj.stale("fit")
            return self._json(d)
        m = re.match(r"^/api/plates/([\w.-]+)$", path)
        if m and m.group(1) in _projects():
            proj = Project(m.group(1))
            d = _read_json(proj.build_dir / "plate" / "plates.json")
            if d is None and (proj.result("slice") or {}).get("plates"):
                from . import plate
                plate.extract(proj)
                d = _read_json(proj.build_dir / "plate" / "plates.json")
            d = d or {"plates": []}
            d["stale"] = proj.stale("slice")
            return self._json(d)
        m = re.match(r"^/api/physics/([\w.-]+)$", path)
        if m and m.group(1) in _projects():
            from urllib.parse import parse_qs
            q = parse_qs(urlparse(self.path).query)
            rpm = max(10.0, min(1500.0, float(q.get("rpm", ["120"])[0])))
            return self._json(_physics(m.group(1), rpm))
        m = re.match(r"^/files/([\w.-]+)/(.+)$", path)
        if m and m.group(1) in _projects():
            base = (config.PROJECTS / m.group(1)).resolve()
            f = (base / m.group(2)).resolve()
            if base in f.parents and f.is_file() and f.suffix in (".stl", ".png", ".gif", ".html", ".json"):
                return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            return self._send(404, b"not found", "text/plain")
        m = re.match(r"^/api/live/([\w.-]+)/info$", path)
        if m and m.group(1) in _projects():
            try:
                from . import live
                s = live.get(m.group(1))
            except Exception as e:
                return self._json({"error": f"{type(e).__name__}: {e}"})
            ph = Project(m.group(1)).result("physics") or {}
            return self._json({"driver": s.drv, "followers": s.followers, "stale": s.stale,
                               "bodies": [{"rep": b["rep"], "kind": b["kind"], "parts": b["parts"]} for b in s.model["bodies"]],
                               "jump_rpm": ph.get("jump_rpm"), "scan": ph.get("scan", [])})
        m = re.match(r"^/api/live/([\w.-]+)/stream$", path)
        if m and m.group(1) in _projects():
            try:
                from . import live
                s = live.get(m.group(1))
            except Exception as e:
                return self._json({"error": str(e)})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seen = -1
            try:
                while s.alive:
                    s.last_seen = time.time()
                    if s.version != seen and s.frame:
                        seen = s.version
                        self.wfile.write(f"data: {json.dumps(s.frame)}\n\n".encode())
                        self.wfile.flush()
                    time.sleep(1 / 40)
            except (BrokenPipeError, ConnectionResetError):
                return
            return
        if path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seen = WATCHER.version
            try:
                self.wfile.write(b": hello\n\n")
                self.wfile.flush()
                while True:
                    with WATCHER.cond:
                        WATCHER.cond.wait(timeout=15)
                        v, changed = WATCHER.version, dict(WATCHER.changed)
                    if v != seen:
                        seen = v
                        self.wfile.write(f"data: {json.dumps({'changed': changed})}\n\n".encode())
                    else:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        return self._send(404, b"not found", "text/plain")


def _do_post(self):
    path = unquote(urlparse(self.path).path)
    m = re.match(r"^/api/live/([\w.-]+)/control$", path)
    if not (m and m.group(1) in _projects()):
        return self._send(404, b"not found", "text/plain")
    n = int(self.headers.get("Content-Length") or 0)
    try:
        msg = json.loads(self.rfile.read(n) or b"{}")
        from . import live
        live.get(m.group(1)).control(msg)
        return self._json({"ok": True})
    except Exception as e:
        return self._json({"error": f"{type(e).__name__}: {e}"})


Handler.do_POST = _do_post


def serve(port: int = 8765):
    PREVIEWER.start()
    WATCHER.start()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"forge studio → http://127.0.0.1:{port}", flush=True)
    srv.serve_forever()
