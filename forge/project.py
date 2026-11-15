"""A project = spec.yaml + design.py + journal.md, and a build/ folder of generated,
hash-stamped results. Every stage writes build/results/<stage>.json carrying the
build hash and per-part geometry hashes; `stale()` compares them to the current
build, so an outdated result can never pass a gate."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import yaml

from . import __version__, config
from .config import ForgeError
from .dsl import Design

STAGES = ["build", "check", "orient", "fit", "sim", "slice", "render", "report"]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _ns(d):
    if isinstance(d, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in d.items()})
    return d


@dataclass
class Project:
    name: str

    @property
    def dir(self) -> Path:
        return config.PROJECTS / self.name

    @property
    def build_dir(self) -> Path:
        return self.dir / "build"

    @property
    def results_dir(self) -> Path:
        return self.build_dir / "results"

    def exists(self) -> bool:
        return (self.dir / "spec.yaml").exists()

    def require(self) -> "Project":
        if not self.exists():
            raise ForgeError(f"No project at {self.dir} (expected spec.yaml). Try `forge new {self.name}`.")
        return self

    # ---------- inputs ----------
    @property
    def spec(self) -> dict:
        return yaml.safe_load((self.dir / "spec.yaml").read_text()) or {}

    def source_hash(self) -> str:
        h = hashlib.sha256()
        for f in ("spec.yaml", "design.py"):
            p = self.dir / f
            h.update(f.encode() + (p.read_bytes() if p.exists() else b""))
        # material data, rules, fit clearances and calibration feed every verdict: changing
        # them must make results stale and invalidate a print approval
        # the verification code itself: a changed check must re-flag old results (studio/render excluded)
        code = [config.PKG / f for f in ("geometry.py", "stages.py", "motion.py", "physics.py", "slicer.py", "printer.py",
                                          "orient.py", "dsl.py")]
        code += sorted((config.PKG / "checks").glob("*.py")) + sorted((config.PKG / "sim").glob("*.py"))
        for p in code:
            h.update(p.name.encode() + p.read_bytes())
        for p in sorted(config.DATA.glob("*.yaml")) + [config.PROJECTS / "_calibration" / "fits.yaml"]:
            if p.exists():
                h.update(p.name.encode() + p.read_bytes())
        h.update(__version__.encode())
        return h.hexdigest()

    def load_design(self, overrides: dict | None = None) -> Design:
        path = self.dir / "design.py"
        mod_name = f"forge_design_{self.name}"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)  # type: ignore
        params = {**(self.spec.get("params") or {}), **(overrides or {})}
        d = mod.build(_ns(params))
        if not isinstance(d, Design):
            raise ForgeError("design.py build(p) must return forge.dsl.Design")
        return d

    # ---------- results ----------
    def manifest(self) -> dict:
        p = self.build_dir / "manifest.json"
        if not p.exists():
            raise ForgeError(f"{self.name} has not been built. Run `forge build {self.name}`.")
        return json.loads(p.read_text())

    def save(self, stage: str, data: dict) -> Path:
        m = self.manifest()
        data = {
            "stage": stage, "at": now(), "forge": __version__,
            "build_hash": m["build_hash"],
            "part_hashes": {k: v["hash"] for k, v in m["parts"].items()},
            **data,
        }
        self.results_dir.mkdir(parents=True, exist_ok=True)
        p = self.results_dir / f"{stage}.json"
        p.write_text(json.dumps(data, indent=2, default=_json_default))
        return p

    def result(self, stage: str) -> dict | None:
        p = self.results_dir / f"{stage}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def stale(self, stage: str) -> str | None:
        """None if the stage result is current; otherwise a reason string."""
        r = self.result(stage)
        if r is None:
            return "not run"
        try:
            m = self.manifest()
        except ForgeError:
            return "not built"
        if stage != "build" and self.source_hash() != m["source_hash"]:
            return "design/spec changed since build"
        if r.get("build_hash") != m["build_hash"]:
            return "computed from an older build"
        return None

    def journal(self, text: str, author: str = "agent", kind: str = "note") -> None:
        p = self.dir / "journal.md"
        icon = {"note": "📝", "decision": "🧭", "human": "🧑", "check": "✅", "warn": "⚠️", "gate": "🚦"}.get(kind, "•")
        line = f"\n- **{now()}** {icon} `{author}` — {text.strip()}\n"
        with p.open("a") as f:
            f.write(line)


def _json_default(o):
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    return str(o)
