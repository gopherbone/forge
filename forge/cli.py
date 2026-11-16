"""forge CLI. Exit codes: 0 ok, 1 a check failed, 2 usage/tool error."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import traceback

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__, config
from .config import ForgeError
from .project import Project

con = Console(highlight=False)
STYLE = {"pass": "bold green", "warn": "bold yellow", "fail": "bold red", "info": "cyan", "—": "dim"}
GLYPH = {"pass": "●", "warn": "▲", "fail": "✖", "info": "◆", "—": "○"}
KIND = {"verified": "cyan", "measured": "blue", "heuristic": "yellow", "estimated": "magenta"}


def banner(sub: str = ""):
    t = Text()
    t.append("▟▙ forge ", style="bold cyan")
    t.append(f"v{__version__}", style="dim")
    if sub:
        t.append(f"  ·  {sub}", style="bold")
    con.print(t)


def st(s: str) -> Text:
    return Text(f"{GLYPH.get(s, '•')} {s}", style=STYLE.get(s, ""))


def checks_table(rows, title=None):
    t = Table(title=title, title_justify="left", header_style="dim", box=None, pad_edge=False, expand=False)
    for c in ("", "part", "check", "evidence", "value", "detail"):
        t.add_column(c, overflow="fold", max_width=60 if c == "detail" else None)
    order = {"fail": 0, "warn": 1, "info": 2, "pass": 3}
    for part, c in sorted(rows, key=lambda r: order[r[1]["status"]]):
        v = c.get("value")
        vs = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
        t.add_row(st(c["status"]), part, c["name"], Text(c["kind"], style=KIND.get(c["kind"], "")),
                  vs[:40], Text(c.get("detail") or "", style="dim"))
    con.print(t)


def _proj(name) -> Project:
    return Project(name).require()


def _stage(label, fn, *a, **kw):
    t0 = time.time()
    with con.status(f"[cyan]{label}…"):
        r = fn(*a, **kw)
    con.print(f"  [green]✓[/] {label} [dim]{time.time() - t0:.1f}s[/]")
    return r


def cmd_doctor(a):
    banner("doctor")
    t = Table(box=None, header_style="dim")
    t.add_column("")
    t.add_column("component")
    t.add_column("detail", style="dim")
    ok = True

    def row(good, name, det):
        nonlocal ok
        ok &= good
        t.add_row(st("pass" if good else "fail"), name, det)
    try:
        import build123d, gmsh, pyvista, trimesh  # noqa
        row(True, "python CAD/mesh stack", f"build123d · trimesh {trimesh.__version__} · gmsh {gmsh.__version__} · pyvista {pyvista.__version__}")
    except Exception as e:
        row(False, "python CAD/mesh stack", str(e))
    try:
        p = config.ccx_path()
        v = subprocess.run([str(p), "-v"], capture_output=True, text=True).stdout.strip().splitlines()
        row(True, "CalculiX FEA", f"{p} · {v[-1] if v else ''}")
    except Exception as e:
        row(False, "CalculiX FEA", str(e))
    try:
        p = config.bambu_path()
        row(True, "Bambu Studio CLI", str(p))
    except Exception as e:
        row(False, "Bambu Studio CLI", str(e))
    try:
        from . import printer
        pr = printer.load()
        s = pr.summary()
        row(s["bed_mm"] == [256.0, 256.0, 250.0], "X1C presets (flattened)",
            f"{s['machine']} · bed {s['bed_mm']} · {s['process']} · {s['filament']} ({s['filament_type']})")
    except Exception as e:
        row(False, "X1C presets", str(e))
    row(True, "fit clearances", "calibrated" if config.fits_calibrated() else "uncalibrated defaults (run `forge coupon`)")
    con.print(t)
    return 0 if ok else 2


def cmd_new(a):
    from .templates import scaffold
    p = scaffold(a.name, a.title or a.name.replace("-", " ").replace("_", " ").title())
    banner(f"new project {a.name}")
    con.print(f"  created [bold]{p.dir.relative_to(config.ROOT)}[/]: spec.yaml · design.py · journal.md")
    return 0


def cmd_stage(a):
    from . import stages
    proj = _proj(a.project)
    banner(f"{a.cmd} {proj.name}")
    fn = {"build": stages.build, "orient": stages.orient, "check": stages.check, "fit": stages.fit,
          "slice": stages.slice_}[a.cmd]
    if a.cmd == "build":
        r = _stage("build", fn, proj)
        for n, v in r["manifest"]["parts"].items():
            con.print(f"    {n}: {v['volume_mm3'] / 1000:.2f} cm³  bbox {v['bbox_mm']}  [dim]{v['hash'][:10]}[/]")
        return 1 if r["status"] == "fail" else 0
    r = _stage(a.cmd, fn, proj)
    return _print_stage(proj, a.cmd)


def _print_stage(proj, stage):
    r = proj.result(stage)
    if stage == "check":
        checks_table([(p, c) for p, v in r["parts"].items() for c in v["checks"]])
        for p, v in r["parts"].items():
            con.print(f"  [dim]{p} orientation {v['orientation']['euler']} ({v['orientation']['source']})[/]")
    elif stage == "fit":
        checks_table([("assembly", c) for c in r["checks"]])
    elif stage == "orient":
        for p, v in r["parts"].items():
            t = Table(title=f"{p}: orientation candidates (lower score = better)", title_justify="left", box=None, header_style="dim")
            for c in ("pose", "euler°", "support mm²", "height", "contact mm²", "min SF", "score"):
                t.add_column(c)
            for i, row in enumerate(v["candidates"][:6]):
                t.add_row(("★ " if i == 0 else "  ") + row["name"], str(row["euler"]), str(row["support_mm2"]), str(row["height_mm"]),
                          str(row["contact_mm2"]), str(row.get("sf_min", "—")), str(row["score"]), style="bold" if i == 0 else "")
            con.print(t)
            if v["locked"]:
                con.print(f"  [yellow]locked in design.py:[/] {v['locked']}")
    elif stage == "sim":
        for c in r["cases"]:
            ev = c["eval"]
            con.print(Panel.fit(
                f"[bold]{c['name']}[/] on {c['part']} · {'large-deflection' if c['nonlinear'] else 'linear'} · {c['use']}\n"
                f"reaction {abs(c['load_force_n']):.2f} N · max disp {c['disp_max_mm']:.3f} mm · mesh {c['mesh']['elements']} el\n"
                f"von Mises {ev['von_mises_max_mpa']:.1f} MPa · across-layer {ev['interlayer_tension_max_mpa']:.1f} MPa · "
                f"SF {ev['sf']} ({ev['governing']}) · strain {100 * ev['strain_max']:.2f}%"
                + (f" ({100 * ev['strain_util']:.0f}% of allowable)" if 'strain_util' in ev else ""),
                border_style="magenta"))
            checks_table([(c["part"], k) for k in c["checks"]])
    elif stage == "slice":
        checks_table([(p, c) for p, v in r["parts"].items() for c in v["checks"]])
        for p in r["plates"]:
            s = p["stats"]
            con.print(f"  [bold]{p['name']}.3mf[/]  {s.get('time_str', '')} · {s.get('filament_g', 0):.1f} g "
                      f"(support {s.get('support_g', 0):.1f} g) · {s.get('cost', 0):.2f}")
    return 1 if r.get("status") == "fail" else 0


def cmd_sim(a):
    from . import stages
    proj = _proj(a.project)
    banner(f"sim {proj.name}")
    _stage("FEA (gmsh + CalculiX)" + ("" if a.fast else " with mesh-convergence pass"), stages.sim, proj,
           converge=not a.fast, only=a.case)
    return _print_stage(proj, "sim")


def cmd_render(a):
    from . import render
    proj = _proj(a.project)
    banner(f"render {proj.name}")
    files = _stage("renders", render.render_all, proj, turntable=not a.no_turntable)
    for k, v in files.items():
        con.print(f"    [dim]{v}[/]")
    return 0


def cmd_report(a):
    from . import report
    proj = _proj(a.project)
    banner(f"report {proj.name}")
    p = _stage("traveller", report.write, proj)
    con.print(f"  → {p}")
    return 0


def cmd_run(a):
    from . import report, stages
    proj = _proj(a.project)
    banner(f"run {proj.name}")
    t0 = time.time()
    last = [time.time()]

    def log(s):
        con.print(f"  [green]✓[/] [dim]{time.time() - last[0]:5.1f}s[/]  → {s}" if s != "build" else f"  [cyan]→[/] {s}")
        last[0] = time.time()
    with con.status("[cyan]running pipeline…"):
        stages.run_all(proj, converge=not a.fast, renders=not a.no_render, log=log)
    return _summary(proj, time.time() - t0)


def _summary(proj, dt=None):
    from . import gate, stages
    s = stages.status(proj)
    t = Table(box=None, header_style="dim", title=f"{proj.name} pipeline", title_justify="left")
    for c in ("stage", "result", "freshness", "at"):
        t.add_column(c)
    for k, v in s.items():
        t.add_row(k, st(v["status"]), Text(v["stale"] or "current", style="red" if v["stale"] else "green"), Text(v["at"] or "", style="dim"))
    con.print(t)
    summ = proj.build_dir / "summary.json"
    if summ.exists():
        sm = json.loads(summ.read_text())
        bad = [r for r in sm["rows"] if r["status"] in ("fail", "warn")]
        if bad:
            checks_table([(r["part"], r) for r in bad], title="needs attention")
        k = sm["kpis"]
        con.print("  " + "  ·  ".join(f"[bold]{v}[/] [dim]{l}[/]" for l, v in k.items()))
    gs = gate.gate_status(proj)
    con.print("  gates: " + "   ".join(f"{'[green]●' if g['approved'] else '[dim]○'} {n}[/]" for n, g in gs.items()))
    if (proj.build_dir / "traveller.html").exists():
        con.print(f"  traveller → [link=file://{proj.build_dir / 'traveller.html'}]{proj.build_dir / 'traveller.html'}[/link]")
    if dt:
        con.print(f"  [dim]{dt:.1f}s[/]")
    rep = proj.result("report") or {}
    return 1 if rep.get("status") == "fail" else 0


def cmd_status(a):
    proj = _proj(a.project)
    banner(f"status {proj.name}")
    return _summary(proj)


def cmd_list(a):
    banner("projects")
    for p in sorted(config.PROJECTS.glob("*/spec.yaml")):
        proj = Project(p.parent.name)
        rep = proj.result("report") or {}
        con.print(f"  {GLYPH.get(rep.get('status', '—'), '○')} [bold]{proj.name}[/]  [dim]{proj.spec.get('title', '')}[/]")
    return 0


def cmd_note(a):
    proj = _proj(a.project)
    proj.journal(a.text, author=a.author, kind=a.kind)
    con.print(f"[green]✓[/] journal ← [{a.author}] {a.text}")
    return 0


def cmd_approve(a):
    from . import gate
    proj = _proj(a.project)
    banner(f"approve {proj.name} · {a.gate}")
    r = gate.approve(proj, a.gate, a.note or "")
    con.print(f"[green]✓ approved[/] {a.gate} by {r['by']} at {r['at']}")
    return 0


def cmd_release(a):
    from . import gate
    proj = _proj(a.project)
    banner(f"release {proj.name}")
    files = gate.release(proj)
    for f in files:
        con.print(f"  [green]✓[/] {f}")
    con.print("  Open in Bambu Studio and send it from there. forge never talks to the printer.")
    return 0


def cmd_open(a):
    proj = _proj(a.project)
    subprocess.run(["open", str(proj.build_dir / "traveller.html")])
    return 0


def cmd_physics(a):
    from . import physics
    proj = _proj(a.project)
    banner(f"physics {proj.name}")
    r = _stage("MuJoCo" + (" + speed scan" if a.scan else ""), physics.run, proj, rpm=a.rpm, do_scan=a.scan)
    t = Table(box=None, header_style="dim", title=f"at {a.rpm:g} rpm", title_justify="left")
    for c in ("body", "joint", "max lift", "off cam", "jumps"):
        t.add_column(c)
    for k, v in r["metrics"].items():
        t.add_row(k, v["kind"], f"{v['max_lift']} {v['unit']}", f"{v['off_cam_pct']}%", st("warn" if v["jumps"] else "pass"))
    con.print(t)
    con.print(f"  crank torque peak [bold]{r['torque_peak_nmm']}[/] N·mm · contact pairs {len(r['pairs'])}")
    if a.scan:
        for row in r["scan"]:
            con.print(f"  {row['rpm']:>5} rpm  {'jumps: ' + ', '.join(row['jumps']) if row['jumps'] else 'on cam'}  [dim]{row['torque_peak_nmm']} N·mm[/]")
        con.print(f"  first jump: [bold]{r['jump_rpm'] or 'none'}[/] rpm")
    return 0


def cmd_preview(a):
    from . import preview
    r = preview.preview(_proj(a.project))
    if r["error"]:
        con.print(f"[red]✖ {r['error']['type']}: {r['error']['message']}[/]")
        return 1
    con.print(f"[green]✓[/] preview {len(r['parts'])} parts in {r['seconds']}s")
    return 0


def cmd_studio(a):
    from . import studio
    banner(f"studio · http://127.0.0.1:{a.port}")
    studio.serve(a.port)
    return 0


def cmd_flex(a):
    from .sim import flexure
    banner(f"flex {a.kind}")
    if a.kind == "cantilever":
        r = flexure.cantilever_snap(a.L, a.t, a.b, a.y, a.material, taper=a.taper, angle_deg=a.angle, use=a.use)
    else:
        r = flexure.living_hinge(a.L, a.t, a.angle, a.material, use=a.use)
    for k, v in r.items():
        con.print(f"  {k:>18}  [bold]{v}[/]")
    return 1 if r["util"] > 1 else 0


def cmd_search(a):
    from . import search
    banner(f"search {a.project}")
    s = search.run(a.project, a.spec, budget=a.budget, workers=a.workers, seed=a.seed,
                   log=lambda m: con.print(f"[dim]{m}[/]"))
    print(search.format_summary(s))
    return 0 if s["best_is_feasible"] else 1


def cmd_coupon(a):
    from . import coupon
    p = coupon.create()
    banner("coupon")
    con.print(f"  created {p.dir}. Run [bold]forge run {p.name}[/], print it, then [bold]forge calibrate[/].")
    return 0


def cmd_calibrate(a):
    from . import coupon
    p = coupon.calibrate(a.press, a.snug, a.sliding, a.loose, a.note or "")
    con.print(f"[green]✓[/] wrote {p}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="forge", description="Verifiable design-for-print pipeline (Bambu Lab X1C)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check the toolchain").set_defaults(fn=cmd_doctor)
    sub.add_parser("list", help="list projects").set_defaults(fn=cmd_list)
    p = sub.add_parser("new", help="scaffold a project")
    p.add_argument("name")
    p.add_argument("--title")
    p.set_defaults(fn=cmd_new)
    for c, h in [("build", "run design.py, export STEP/STL, write manifest"), ("orient", "search print orientations"),
                 ("check", "printability checks in print orientation"), ("fit", "assembly interference + clearance"),
                 ("slice", "slice with Bambu Studio, verify presets, measure support")]:
        p = sub.add_parser(c, help=h)
        p.add_argument("project")
        p.set_defaults(fn=cmd_stage)
    p = sub.add_parser("sim", help="FEA load cases")
    p.add_argument("project")
    p.add_argument("--case")
    p.add_argument("--fast", action="store_true", help="skip the mesh-convergence pass")
    p.set_defaults(fn=cmd_sim)
    p = sub.add_parser("render", help="renders for review")
    p.add_argument("project")
    p.add_argument("--no-turntable", action="store_true")
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("report", help="write the traveller (review packet)")
    p.add_argument("project")
    p.set_defaults(fn=cmd_report)
    p = sub.add_parser("run", help="the whole pipeline")
    p.add_argument("project")
    p.add_argument("--fast", action="store_true")
    p.add_argument("--no-render", action="store_true")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("status", help="pipeline + gate status")
    p.add_argument("project")
    p.set_defaults(fn=cmd_status)
    p = sub.add_parser("note", help="add a journal entry")
    p.add_argument("project")
    p.add_argument("text")
    p.add_argument("--author", default="agent")
    p.add_argument("--kind", default="note", choices=["note", "decision", "human", "check", "warn", "gate"])
    p.set_defaults(fn=cmd_note)
    p = sub.add_parser("approve", help="(humans only, interactive) approve a gate")
    p.add_argument("project")
    p.add_argument("gate", choices=["spec", "concept", "print"])
    p.add_argument("--note")
    p.set_defaults(fn=cmd_approve)
    p = sub.add_parser("release", help="copy approved, sliced plates to release/")
    p.add_argument("project")
    p.set_defaults(fn=cmd_release)
    p = sub.add_parser("open", help="open the traveller")
    p.add_argument("project")
    p.set_defaults(fn=cmd_open)
    p = sub.add_parser("physics", help="MuJoCo dynamics inferred from the motion sweep")
    p.add_argument("project")
    p.add_argument("--rpm", type=float, default=120)
    p.add_argument("--scan", action="store_true", help="also scan crank speeds for follower jump")
    p.set_defaults(fn=cmd_physics)
    p = sub.add_parser("preview", help="fast geometry-only preview (used by studio hot reload)")
    p.add_argument("project")
    p.set_defaults(fn=cmd_preview)
    p = sub.add_parser("studio", help="live dashboard: watch agents build and verify")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(fn=cmd_studio)
    p = sub.add_parser("search", help="cheap parallel parameter search (exploratory; no tokens)")
    p.add_argument("project")
    p.add_argument("spec", help="search spec YAML (vary/constraints/objective), e.g. search/fit.yaml")
    p.add_argument("--budget", type=int)
    p.add_argument("--workers", type=int)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(fn=cmd_search)
    p = sub.add_parser("flex", help="closed-form flexure sizing")
    p.add_argument("kind", choices=["cantilever", "hinge"])
    p.add_argument("--L", type=float, required=True, help="length mm")
    p.add_argument("--t", type=float, required=True, help="thickness mm")
    p.add_argument("--b", type=float, default=5.0, help="width mm (cantilever)")
    p.add_argument("--y", type=float, default=1.0, help="tip deflection mm (cantilever)")
    p.add_argument("--angle", type=float, default=30.0, help="lead-in angle (cantilever) or bend angle (hinge), deg")
    p.add_argument("--taper", type=float, default=1.0)
    p.add_argument("--material", default="PETG")
    p.add_argument("--use", default="once", choices=["once", "repeated"])
    p.set_defaults(fn=cmd_flex)
    sub.add_parser("coupon", help="generate the clearance calibration coupon").set_defaults(fn=cmd_coupon)
    p = sub.add_parser("calibrate", help="record coupon results (per-side gaps that worked)")
    for k in ("press", "snug", "sliding", "loose"):
        p.add_argument(f"--{k}", type=float, required=True)
    p.add_argument("--note")
    p.set_defaults(fn=cmd_calibrate)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except ForgeError as e:
        con.print(f"[bold red]✖[/] {e}")
        return 2
    except Exception:
        con.print_exception(max_frames=6)
        return 2


if __name__ == "__main__":
    sys.exit(main())
