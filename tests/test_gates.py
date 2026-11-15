"""Gate logic on a throwaway project in a temp dir (never touches real projects)."""
import json
import pytest

from forge import config, gate
from forge.config import ForgeError
from forge.project import Project


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS", tmp_path)
    d = tmp_path / "t"
    d.mkdir()
    (d / "spec.yaml").write_text("title: t\nparams: {}\n")
    (d / "design.py").write_text(
        "from build123d import Box\nfrom forge.dsl import Design, Part\n"
        "def build(p):\n    return Design(parts=[Part('a', Box(10, 10, 10))])\n")
    from forge import geometry
    p = Project("t")
    geometry.build(p)
    return p


def test_approve_refuses_without_a_tty(tmp_project, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(ForgeError, match="interactive terminal"):
        gate.approve(tmp_project, "spec")
    assert not (tmp_project.dir / "approvals.json").exists()


def test_release_blocked_without_print_approval(tmp_project):
    with pytest.raises(ForgeError, match="Release blocked"):
        gate.release(tmp_project)


def test_print_approval_binds_to_build_hash(tmp_project):
    m = tmp_project.manifest()
    rec = [{"gate": "print", "by": "x", "at": "now", "build_hash": m["build_hash"], "spec_hash": "", "note": ""}]
    (tmp_project.dir / "approvals.json").write_text(json.dumps(rec))
    assert gate.gate_status(tmp_project)["print"]["approved"]
    (tmp_project.dir / "approvals.json").write_text(json.dumps([{**rec[0], "build_hash": "stale"}]))
    assert not gate.gate_status(tmp_project)["print"]["approved"]


def test_data_change_makes_results_stale(tmp_project, monkeypatch, tmp_path):
    h0 = tmp_project.source_hash()
    data = tmp_path / "data"
    data.mkdir()
    for f in config.DATA.glob("*.yaml"):
        (data / f.name).write_text(f.read_text())
    monkeypatch.setattr(config, "DATA", data)
    assert tmp_project.source_hash() == h0
    (data / "materials.yaml").write_text((data / "materials.yaml").read_text() + "\n# edited\n")
    assert tmp_project.source_hash() != h0


def _proj(tmp_path, monkeypatch, name, design, params="{}"):
    monkeypatch.setattr(config, "PROJECTS", tmp_path)
    d = tmp_path / name
    d.mkdir()
    (d / "spec.yaml").write_text(f"title: {name}\nparams: {params}\n")
    (d / "design.py").write_text(design)
    from forge import geometry
    p = Project(name)
    geometry.build(p)
    return p


RET = '''
from build123d import Box, Pos, Align
from forge.dsl import Design, Part, Fit
def build(p):
    a = Box(20, 20, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))
    b = Pos(0, 0, 5.4) * Box(20, 20, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return Design(parts=[Part("a", a), Part("b", b)], fits=[Fit("a", "b", "loose", retention={ret})])
'''


def test_retention_checks(tmp_path, monkeypatch):
    from forge import stages
    for ret, want in [("None", "warn"), ("'gravity'", "warn"), ("'snap'", "warn"), ("'captured'", "pass")]:
        p = _proj(tmp_path, monkeypatch, f"r{len(ret)}{want}", RET.format(ret=ret))
        c = next(c for c in stages.fit(p)["checks"] if c["id"].startswith("ret:"))
        assert c["status"] == want, (ret, c)


def test_code_change_makes_results_stale(tmp_path, monkeypatch):
    p = _proj(tmp_path, monkeypatch, "cc", RET.format(ret="'captured'"))
    h0 = p.source_hash()
    pkg = tmp_path / "pkg"
    import shutil
    shutil.copytree(config.PKG, pkg)
    monkeypatch.setattr(config, "PKG", pkg)
    assert p.source_hash() == h0
    (pkg / "checks" / "printability.py").write_text((pkg / "checks" / "printability.py").read_text() + "\n# changed\n")
    assert p.source_hash() != h0


def test_spec_gate_ignores_param_tuning_but_not_requirements(tmp_path, monkeypatch):
    from forge import gate
    p = _proj(tmp_path, monkeypatch, "sg", RET.format(ret="'captured'"))
    h0 = gate.spec_hash(p)
    s = (p.dir / "spec.yaml").read_text()
    (p.dir / "spec.yaml").write_text(s.replace("params: {}", "params: {width: 12}"))
    assert gate.spec_hash(p) == h0                       # dimension tuning keeps the approval
    (p.dir / "spec.yaml").write_text(s + "requirements:\n  - {id: R1, text: changed}\n")
    assert gate.spec_hash(p) != h0                       # a requirement change invalidates it
