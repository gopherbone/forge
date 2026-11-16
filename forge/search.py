"""forge search: cheap, parallel parameter exploration for agents.

An agent describes WHAT to vary and WHAT good looks like; forge tries many variants without
spending model tokens, and hands back a short summary: the best feasible candidates, which
constraints bind, which parameters matter, and the ranges that work.

    forge search <project> <spec.yaml> [--budget N] [--workers K] [--seed S]

Spec (YAML; a file in projects/<p>/search/ by convention):

    vary:                         # continuous [lo, hi] | {int: [lo, hi]} | {choice: [a, b, c]}
      lo: [0.10, 0.35]
      teeth: {int: [14, 22]}
      pa: {choice: [14.5, 20, 25]}
    poses: 4                      # optional: evaluate at N motion-param values (the design's Motion); gaps take the worst pose
    hook: evaluate                # optional: design.py `def evaluate(design, p) -> dict` of extra metrics (closed-form, 2D studies...)
    constraints:                  # python expressions over the metrics below
      - valid
      - gap['pinion|frame'] >= 0.15
      - collisions == 0
    objective: minimize lift      # or "maximize <expr>"
    budget: 120
    workers: 6

Metrics per sample: p.<name> (the sample's params), valid, mass_g, volume[part], bbox (x, y, z mm of the assembly), gap['a|b'] and
overlap['a|b'] for every declared Fit (inside its region, worst over poses), collisions (undeclared
overlapping pairs), plus whatever the hook returns.

Strategy (multi-fidelity is up to the hook; geometry is the expensive tier):
  1. Latin-hypercube sample ~55% of the budget over the whole space.
  2. Evolution: perturb the best candidates with a shrinking step (choices: keep the parent's value,
     explore 20%), spending the rest. Feasible beats infeasible; then the objective; infeasible
     candidates are ranked by total normalised constraint violation.
Every sample is cached by (design source, params), so re-running or widening a search is cheap.

This is EXPLORATION at nominal geometry. Nothing here is verified: apply the chosen params to
spec.yaml yourself, then `forge run` proves them. Search never edits the project.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import yaml

from .config import ForgeError

_CMP = re.compile(r"^(.*?)(>=|<=|==|>|<)(.*)$")


# ---------------------------------------------------------------- space
class Space:
    def __init__(self, vary: dict):
        if not vary:
            raise ForgeError("search spec needs a non-empty `vary:` block")
        self.dims = []
        for name, v in vary.items():
            if isinstance(v, dict) and "choice" in v:
                self.dims.append((name, "choice", list(v["choice"])))
            elif isinstance(v, dict) and "int" in v:
                lo, hi = v["int"]
                self.dims.append((name, "int", (int(lo), int(hi))))
            elif isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
                self.dims.append((name, "float", (float(v[0]), float(v[1]))))
            else:
                raise ForgeError(f"vary.{name}: use [lo, hi], {{int: [lo, hi]}} or {{choice: [...]}}")

    def from_unit(self, u):
        out = {}
        for (name, kind, dom), x in zip(self.dims, u):
            x = min(max(x, 0.0), 1.0 - 1e-12)
            if kind == "float":
                out[name] = round(dom[0] + x * (dom[1] - dom[0]), 4)
            elif kind == "int":
                out[name] = int(dom[0] + math.floor(x * (dom[1] - dom[0] + 1)))
            else:
                out[name] = dom[int(x * len(dom))]
        return out

    def to_unit(self, p):
        u = []
        for name, kind, dom in self.dims:
            v = p[name]
            if kind == "float":
                u.append((v - dom[0]) / ((dom[1] - dom[0]) or 1))
            elif kind == "int":
                u.append((v - dom[0] + 0.5) / (dom[1] - dom[0] + 1))
            else:
                u.append((dom.index(v) + 0.5) / len(dom))
        return u

    def lhs(self, n, rng):
        cols = []
        for _ in self.dims:
            perm = list(range(n))
            rng.shuffle(perm)
            cols.append([(perm[i] + rng.random()) / n for i in range(n)])
        return [self.from_unit([c[i] for c in cols]) for i in range(n)]

    def mutate(self, p, sigma, rng):
        u = self.to_unit(p)
        out = []
        for (name, kind, dom), x in zip(self.dims, u):
            if kind == "choice":
                out.append(rng.random() if rng.random() < 0.2 else x)
            else:
                out.append(min(max(x + rng.gauss(0, sigma), 0.0), 1.0 - 1e-9))
        return self.from_unit(out)


# ---------------------------------------------------------------- evaluation (runs in worker processes)
def _evaluate(project: str, params: dict, poses: int, hook: str | None, root: str | None = None) -> dict:
    t0 = time.time()
    try:
        if root:  # worker processes start fresh: point them at the same projects folder as the caller
            from . import config as _cfg
            _cfg.PROJECTS = Path(root)
        from .geometry import occ_transform, placement_matrix
        from .project import Project
        from .checks.assembly import _bbox_overlap, _clip
        proj = Project(project)
        d0 = proj.load_design(params)
        values = [None]
        if poses and d0.motion is not None:
            mot = d0.motion
            values = list(np.linspace(mot.start, mot.stop, max(int(poses), 1), endpoint=poses == 1))
        gap, overlap, collisions = {}, {}, 0
        m = {"valid": True}
        for v in values:
            d = d0 if v is None else proj.load_design({**params, d0.motion.param: float(v)})
            shapes = {}
            for p in d.parts:
                s = p.shape.part if hasattr(p.shape, "part") else p.shape
                if s is None or not s.is_valid or s.volume <= 0:
                    m["valid"] = False
                shapes[p.name] = occ_transform(s, placement_matrix(p.placement))
            if v is None or "mass_g" not in m:
                from .config import material
                vol = {p.name: float((p.shape.part if hasattr(p.shape, "part") else p.shape).volume) for p in d.parts}
                m["volume"] = {k: round(x, 1) for k, x in vol.items()}
                m["mass_g"] = round(sum(vol[p.name] / 1000 * material(p.material)["density_g_cm3"] for p in d.parts if not p.purchased), 2)
                bb = None
                for s in shapes.values():
                    b = s.bounding_box()
                    bb = b if bb is None else bb.add(b)
                m["bbox"] = [round(bb.size.X, 2), round(bb.size.Y, 2), round(bb.size.Z, 2)]
            declared = {}
            for f in d.fits:
                key = f"{f.a}|{f.b}"
                declared[frozenset((f.a, f.b))] = key
                A, B = shapes[f.a], shapes[f.b]
                AA, BB = (_clip(A, f.region), _clip(B, f.region)) if f.region else (A, B)
                try:
                    g = float(AA.distance_to(BB))
                except Exception:
                    g = float("nan")
                inter = A & B if _bbox_overlap(A, B) else None
                ov = float(inter.volume) if inter is not None else 0.0
                gap[key] = min(gap.get(key, math.inf), g)
                overlap[key] = max(overlap.get(key, 0.0), ov)
            names = list(shapes)
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    a, b = names[i], names[j]
                    if frozenset((a, b)) in declared or not _bbox_overlap(shapes[a], shapes[b]):
                        continue
                    inter = shapes[a] & shapes[b]
                    if inter is not None and inter.volume > 1e-3:
                        collisions += 1
        m["gap"] = {k: round(x, 4) for k, x in gap.items()}
        m["overlap"] = {k: round(x, 4) for k, x in overlap.items()}
        m["collisions"] = collisions
        if hook:
            import sys
            mod = sys.modules.get(f"forge_design_{project}")
            fn = getattr(mod, hook, None)
            if fn is None:
                raise ForgeError(f"design.py has no `{hook}(design, p)` hook")
            from .project import _ns
            extra = fn(d0, _ns({**(proj.spec.get("params") or {}), **params})) or {}
            m.update(extra)
        m["seconds"] = round(time.time() - t0, 2)
        m["p"] = params
        return {"params": params, "metrics": m, "error": None}
    except Exception as e:  # a failed build is information too (infeasible region)
        return {"params": params, "metrics": {"valid": False, "seconds": round(time.time() - t0, 2)},
                "error": f"{type(e).__name__}: {str(e)[:200]}"}


# ---------------------------------------------------------------- scoring
class _Lenient(dict):
    """Missing gap/overlap keys read as NaN so a typo shows up as a violated constraint, not a crash."""
    def __missing__(self, k):
        return float("nan")


def _ns_for(m: dict) -> dict:
    ns = {k: v for k, v in m.items()}
    ns["gap"] = _Lenient(m.get("gap") or {})
    ns["overlap"] = _Lenient(m.get("overlap") or {})
    ns["volume"] = _Lenient(m.get("volume") or {})
    from types import SimpleNamespace
    ns["p"] = SimpleNamespace(**(m.get("p") or {}))      # the sample's params, e.g. objective: maximize p.lip_u
    ns.update(math=math, abs=abs, min=min, max=max)
    return ns


def _eval_expr(expr: str, m: dict):
    try:
        return eval(expr, {"__builtins__": {}}, _ns_for(m))
    except Exception:
        return float("nan")


def _violation(con: str, m: dict) -> float:
    """0 if satisfied; otherwise a positive amount (normalised by the threshold's magnitude)."""
    mt = _CMP.match(con)
    if not mt:
        v = _eval_expr(con, m)
        return 0.0 if v is True or (isinstance(v, (int, float)) and v and not math.isnan(v)) else 1.0
    lhs, op, rhs = mt.group(1).strip(), mt.group(2), mt.group(3).strip()
    a, b = _eval_expr(lhs, m), _eval_expr(rhs, m)
    try:
        a, b = float(a), float(b)
    except Exception:
        return 1.0
    if math.isnan(a) or math.isnan(b):
        return 1.0
    scale = max(abs(b), 1e-3)
    if op in (">=", ">"):
        return max(0.0, (b - a) / scale) + (1e-6 if op == ">" and a == b else 0)
    if op in ("<=", "<"):
        return max(0.0, (a - b) / scale) + (1e-6 if op == "<" and a == b else 0)
    return abs(a - b) / scale


def _objective(spec: str | None):
    if not spec:
        return None, 1.0
    s = spec.strip()
    for word, sign in (("minimize", 1.0), ("minimise", 1.0), ("maximize", -1.0), ("maximise", -1.0)):
        if s.startswith(word):
            return s[len(word):].strip(" :"), sign
    return s, 1.0


def _score(r: dict, cons: list[str], obj_expr, sign):
    if r["error"] or not r["metrics"].get("valid", False):
        return (2, math.inf, math.inf)
    m = r["metrics"]
    viol = sum(_violation(c, m) for c in cons)
    o = _eval_expr(obj_expr, m) if obj_expr else 0.0
    try:
        o = float(o)
    except Exception:
        o = math.nan
    o = sign * o if not math.isnan(o) else math.inf
    return (0 if viol == 0 else 1, viol, o)


# ---------------------------------------------------------------- driver
def _key(proj_dir: Path, params: dict, poses, hook) -> str:
    h = hashlib.sha1()
    h.update((proj_dir / "design.py").read_bytes())
    h.update(json.dumps({"p": params, "poses": poses, "hook": hook}, sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def run(project: str, spec_path: str, budget: int | None = None, workers: int | None = None, seed: int = 0,
        log=print) -> dict:
    from .project import Project
    proj = Project(project)
    sp = Path(spec_path)
    if not sp.is_absolute() and not sp.exists():
        sp = proj.dir / spec_path
    spec = yaml.safe_load(sp.read_text())
    space = Space(spec.get("vary") or {})
    cons = [str(c) for c in (spec.get("constraints") or [])]
    obj_expr, sign = _objective(spec.get("objective"))
    budget = int(budget or spec.get("budget", 60))
    workers = int(workers or spec.get("workers", 4))
    poses, hook = spec.get("poses", 0), spec.get("hook")
    name = sp.stem
    out = proj.build_dir / "search" / name
    out.mkdir(parents=True, exist_ok=True)
    cache_f = out / "cache.jsonl"
    cache = {}
    if cache_f.exists():
        for line in cache_f.read_text().splitlines():
            try:
                r = json.loads(line)
                cache[r["key"]] = r
            except Exception:
                pass
    rng = random.Random(seed)
    results: list[dict] = []
    seen = set()
    t0 = time.time()

    def submit_batch(cands):
        todo = []
        for p in cands:
            k = _key(proj.dir, p, poses, hook)
            if k in seen:
                continue
            seen.add(k)
            if k in cache:
                results.append(cache[k])
            else:
                todo.append((k, p))
        if not todo:
            return
        import multiprocessing as mp
        with ProcessPoolExecutor(max_workers=min(workers, len(todo)), mp_context=mp.get_context("spawn")) as ex:
            from . import config as _cfg
            futs = {ex.submit(_evaluate, project, p, poses, hook, str(_cfg.PROJECTS)): k for k, p in todo}
            with cache_f.open("a") as fh:
                for f in as_completed(futs):
                    r = f.result()
                    r["key"] = futs[f]
                    results.append(r)
                    fh.write(json.dumps(r, default=str) + "\n")
        log(f"  {len(results)}/{budget} evaluated · {time.time() - t0:.0f} s")

    n0 = max(4, int(budget * 0.55))
    submit_batch(space.lhs(n0, rng))
    gen = 0
    while len(results) < budget:
        ranked = sorted(results, key=lambda r: _score(r, cons, obj_expr, sign))
        parents = ranked[:max(3, len(ranked) // 8)]
        frac = len(results) / budget
        sigma = 0.15 * (1 - frac) + 0.03
        lam = min(budget - len(results), max(workers * 2, 8))
        kids = [space.mutate(rng.choice(parents)["params"], sigma, rng) for _ in range(lam)]
        before = len(results)
        submit_batch(kids)
        gen += 1
        if len(results) == before:  # converged onto cached points: widen
            submit_batch(space.lhs(lam, rng))
            if len(results) == before:
                break
    summary = summarize(results, space, cons, obj_expr, sign)
    summary.update(project=project, spec=str(sp), budget=budget, evaluated=len(results), seconds=round(time.time() - t0, 1),
                   evidence="exploratory (nominal geometry, not verified): apply params to spec.yaml, then forge run")
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    (out / "summary.md").write_text(format_summary(summary))
    return summary


def _spearman(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = ~(np.isnan(x) | np.isnan(y) | np.isinf(x) | np.isinf(y))
    if ok.sum() < 5 or np.std(x[ok]) == 0 or np.std(y[ok]) == 0:
        return None
    rx, ry = np.argsort(np.argsort(x[ok])), np.argsort(np.argsort(y[ok]))
    return round(float(np.corrcoef(rx, ry)[0, 1]), 2)


def summarize(results, space, cons, obj_expr, sign) -> dict:
    scored = sorted(((_score(r, cons, obj_expr, sign), r) for r in results), key=lambda t: t[0])
    feas = [r for s, r in scored if s[0] == 0]
    errors = [r for r in results if r["error"]]
    binding = {}
    for r in results:
        if r["error"] or not r["metrics"].get("valid"):
            continue
        for c in cons:
            if _violation(c, r["metrics"]) > 0:
                binding[c] = binding.get(c, 0) + 1
    valid = [r for r in results if not r["error"] and r["metrics"].get("valid")]
    sens = {}
    for name, kind, dom in space.dims:
        xs = [space.to_unit({n: r["params"][n] for n, _, _ in space.dims})[[d[0] for d in space.dims].index(name)] for r in valid]
        row = {}
        if obj_expr and feas:
            fx = [space.to_unit(r["params"])[[d[0] for d in space.dims].index(name)] for r in feas]
            fo = [float(_eval_expr(obj_expr, r["metrics"])) if isinstance(_eval_expr(obj_expr, r["metrics"]), (int, float)) else math.nan for r in feas]
            row["vs_objective"] = _spearman(fx, fo)
        row["vs_feasible"] = _spearman(xs, [1.0 if _score(r, cons, obj_expr, sign)[0] == 0 else 0.0 for r in valid])
        sens[name] = row
    good = feas[:max(3, len(feas) // 10)] if feas else []
    ranges = {}
    for name, kind, dom in space.dims:
        vals = [r["params"][name] for r in good]
        if not vals:
            continue
        ranges[name] = sorted(set(vals)) if kind == "choice" else [min(vals), max(vals)]

    def brief(r):
        m = r["metrics"]
        keep = {k: v for k, v in m.items() if k not in ("volume", "seconds", "p")}
        return {"params": r["params"], "objective": _eval_expr(obj_expr, m) if obj_expr else None, "metrics": keep}
    return {"feasible": len(feas), "valid": len(valid), "errors": len(errors),
            "error_examples": sorted({r["error"] for r in errors})[:3],
            "objective": (("minimize " if sign > 0 else "maximize ") + obj_expr) if obj_expr else None,
            "constraints": cons, "binding": dict(sorted(binding.items(), key=lambda kv: -kv[1])),
            "sensitivity": sens, "good_ranges": ranges,
            "best": [brief(r) for r in feas[:5]] or [brief(r) for _, r in scored[:3] if not r["error"]],
            "best_is_feasible": bool(feas)}


def format_summary(s: dict) -> str:
    L = [f"forge search · {s.get('project')} · {Path(s.get('spec', '')).name}",
         f"{s['evaluated']} evaluated in {s['seconds']} s · {s['valid']} built · {s['feasible']} feasible · {s['errors']} errors",
         f"objective: {s['objective'] or '(none: feasibility only)'}"]
    if s["error_examples"]:
        L.append("errors e.g.: " + " | ".join(s["error_examples"]))
    if s["binding"]:
        L.append("binding constraints (times violated): " + ", ".join(f"{c} ×{n}" for c, n in s["binding"].items()))
    L.append("sensitivity (rank corr; + means higher param → higher objective / more often feasible):")
    for k, v in s["sensitivity"].items():
        L.append(f"  {k:<18} objective {v.get('vs_objective')!s:>6}   feasible {v.get('vs_feasible')!s:>6}")
    if s["good_ranges"]:
        L.append("ranges among the best feasible: " + ", ".join(f"{k} {v}" for k, v in s["good_ranges"].items()))
    L.append("best" + ("" if s["best_is_feasible"] else " (NONE FEASIBLE: least-violating shown)") + ":")
    for i, b in enumerate(s["best"], 1):
        m = b["metrics"]
        extra = {k: v for k, v in m.items() if k not in ("valid", "gap", "overlap")}
        L.append(f"  {i}. {json.dumps(b['params'])}  obj {b['objective']}")
        if m.get("gap"):
            L.append(f"     gap {json.dumps(m['gap'])}")
        if any(v > 0 for v in (m.get("overlap") or {}).values()):
            L.append(f"     overlap {json.dumps({k: v for k, v in m['overlap'].items() if v > 0})}")
        if extra:
            L.append(f"     {json.dumps(extra, default=str)[:300]}")
    L.append(f"evidence: {s['evidence']}")
    return "\n".join(L)
