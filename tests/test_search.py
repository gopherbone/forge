"""forge search: finds the clearance that satisfies a fit + a closed-form hook, reports binding
constraints when nothing is feasible, and reuses its cache."""
import textwrap

from forge import config, search

DESIGN = textwrap.dedent('''
    from build123d import Box, Cylinder, Pos
    from forge.dsl import Design, Part, Fit
    from forge.sim import flexure

    def build(p):
        block = Box(20, 20, 10) - Pos(0, 0, 0) * Cylinder(p.peg_r + p.clear, 12)
        peg = Pos(0, 0, 2) * Cylinder(p.peg_r, 14)
        return Design(parts=[Part("block", block), Part("peg", peg)],
                      fits=[Fit("block", "peg", "sliding", retention="captured")])

    def evaluate(d, p):
        # a made-up snap on the peg: thicker peg -> stiffer -> higher strain at a fixed 1 mm deflection
        r = flexure.cantilever_snap(L=12, t=p.peg_r * 0.6, b=4, y=1.0)
        return {"snap_util": r["util"]}
''')


def _proj(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS", tmp_path)
    d = tmp_path / "s"
    d.mkdir()
    (d / "design.py").write_text(DESIGN)
    (d / "spec.yaml").write_text("title: s\nparams: {peg_r: 3.0, clear: 0.3}\n")
    return d


def _spec(d, cons, budget=16):
    f = d / "fit.yaml"
    f.write_text(textwrap.dedent(f'''
        vary: {{clear: [0.0, 0.5], peg_r: [2.0, 4.0]}}
        hook: evaluate
        constraints: {cons}
        objective: minimize gap['block|peg']
        budget: {budget}
        workers: 4
    '''))
    return f


def test_search_finds_tight_feasible_fit(tmp_path, monkeypatch):
    d = _proj(tmp_path, monkeypatch)
    s = search.run("s", str(_spec(d, ["valid", "gap['block|peg'] >= 0.2", "snap_util <= 0.8"])), log=lambda m: None)
    assert s["best_is_feasible"]
    best = s["best"][0]
    assert 0.2 <= best["metrics"]["gap"]["block|peg"] <= 0.3
    assert best["metrics"]["snap_util"] <= 0.8
    assert s["sensitivity"]["clear"]["vs_objective"] > 0.5      # more clearance -> bigger gap


def test_search_reports_binding_constraint_and_caches(tmp_path, monkeypatch):
    d = _proj(tmp_path, monkeypatch)
    spec = _spec(d, ["valid", "gap['block|peg'] >= 0.9"], budget=8)   # impossible: clear <= 0.5
    s = search.run("s", str(spec), log=lambda m: None)
    assert not s["best_is_feasible"]
    assert "gap['block|peg'] >= 0.9" in s["binding"]
    t = search.run("s", str(spec), log=lambda m: None)                 # all cached
    assert t["seconds"] < s["seconds"]
