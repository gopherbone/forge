"""Review packet: one self-contained HTML 'traveller' per build, plus summary.json.

The traveller is what a human signs off on. It shows every check with its evidence
type (verified / measured / heuristic / estimated), marks stale stages, and shows
which gates have been approved for THIS build hash."""
from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path

from . import config, gate
from .checks import worst
from .project import Project, now

KIND_HELP = {
    "verified": "Exact geometric fact or real slicer output",
    "measured": "Sampled measurement of the real geometry",
    "heuristic": "Rule of thumb about how prints behave",
    "estimated": "Simulation using material data of limited confidence",
}


def _img(proj: Project, rel: str | None, alt: str, cls: str = "") -> str:
    if not rel:
        return ""
    p = proj.dir / rel
    if not p.exists():
        return ""
    mime = "image/gif" if p.suffix == ".gif" else "image/png"
    b = base64.b64encode(p.read_bytes()).decode()
    return f'<img class="{cls}" alt="{html.escape(alt)}" src="data:{mime};base64,{b}">'


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, dict):
        return ", ".join(f"{k.replace('_', ' ')} {_fmt(x)}" for k, x in v.items())
    if isinstance(v, list):
        return ", ".join(_fmt(x) for x in v) if v else "none"
    return str(v)


def _chip(status: str) -> str:
    label = {"pass": "Pass", "warn": "Warn", "fail": "Fail", "info": "Info"}.get(status, status)
    return f'<span class="chip s-{status}">{label}</span>'


def _kind(kind: str) -> str:
    return f'<span class="kind k-{kind}" title="{KIND_HELP.get(kind, "")}">{kind}</span>'


def _hms(s: float) -> str:
    s = int(s or 0)
    return f"{s // 3600}h {s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m {s % 60:02d}s"


def _ledger(rows: list[tuple[str, str, dict]]) -> str:
    out = ['<div class="scroll"><table class="ledger"><thead><tr><th>Stage</th><th>Part</th><th>Check</th>'
           '<th>Evidence</th><th>Result</th><th class="num">Value</th><th class="num">Limit</th></tr></thead><tbody>']
    for stage, part, c in rows:
        out.append(
            f'<tr class="r-{c["status"]}"><td class="mono">{stage}</td><td>{html.escape(part)}</td>'
            f'<td><div class="cname">{html.escape(c["name"])}</div><div class="cdet">{html.escape(c.get("detail") or "")}</div></td>'
            f'<td>{_kind(c["kind"])}</td><td>{_chip(c["status"])}</td>'
            f'<td class="num mono">{html.escape(_fmt(c.get("value")))}</td><td class="num mono">{html.escape(_fmt(c.get("limit")))}</td></tr>')
    out.append("</tbody></table></div>")
    return "".join(out)


def _journal_html(proj: Project) -> str:
    p = proj.dir / "journal.md"
    if not p.exists():
        return "<p class='muted'>No journal entries yet.</p>"
    items = []
    for ln in p.read_text().splitlines():
        m = re.match(r"^- \*\*(.+?)\*\* (\S+) `(.+?)` — (.*)$", ln)
        if m:
            t, icon, who, text = m.groups()
            cls = "human" if who != "agent" and not who.startswith("forge") and "agent" not in who else "agent"
            items.append(f'<li class="j-{cls}"><span class="jt mono">{html.escape(t)}</span>'
                         f'<span class="jw">{html.escape(who)}</span><span class="jx">{html.escape(text)}</span></li>')
    return f'<ol class="journal">{"".join(items[-40:])}</ol>' if items else "<p class='muted'>No journal entries yet.</p>"


CSS = """
:root{
  /* Layout: a print traveller. Header band, KPI strip, verification ledger, then per-part and per-load-case sheets. */
  --bg:#eef1f3; --panel:#ffffff; --ink:#15212b; --muted:#5d6b78; --line:#d5dce2; --accent:#0e7c86; --accent-ink:#ffffff;
  --pass:#1f8a4c; --warn:#b26a00; --fail:#c62839; --info:#4a6fa5;
  --pass-bg:#e3f3ea; --warn-bg:#fbefdc; --fail-bg:#fbe3e6; --info-bg:#e6edf7;
  --k-verified:#0e7c86; --k-measured:#3b6ea5; --k-heuristic:#8a6d1f; --k-estimated:#8b4a9c;
  --viewport:#10161c;
  --f-display:"IBM Plex Sans Condensed","Arial Narrow",system-ui,sans-serif;
  --f-body:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --f-mono:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#0b1014; --panel:#121a21; --ink:#e3e9ee; --muted:#8c9aa7; --line:#24313c; --accent:#38c2c9; --accent-ink:#06181a;
  --pass:#4cc38a; --warn:#f0a83a; --fail:#ff6b7a; --info:#7fa6e0;
  --pass-bg:#10291d; --warn-bg:#2e2210; --fail-bg:#33141a; --info-bg:#142033;
  --k-verified:#38c2c9; --k-measured:#7fa6e0; --k-heuristic:#d9b75a; --k-estimated:#c98bd9; --viewport:#0d1217; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0b1014; --panel:#121a21; --ink:#e3e9ee; --muted:#8c9aa7; --line:#24313c; --accent:#38c2c9; --accent-ink:#06181a;
  --pass:#4cc38a; --warn:#f0a83a; --fail:#ff6b7a; --info:#7fa6e0;
  --pass-bg:#10291d; --warn-bg:#2e2210; --fail-bg:#33141a; --info-bg:#142033;
  --k-verified:#38c2c9; --k-measured:#7fa6e0; --k-heuristic:#d9b75a; --k-estimated:#c98bd9; --viewport:#0d1217; color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:15px/1.55 var(--f-body);margin:0}
.wrap{max-width:1180px;margin:0 auto;padding-block:28px 64px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));display:grid;gap:28px}
h1,h2,h3{font-family:var(--f-display);text-wrap:balance;margin:0;letter-spacing:.01em}
h1{font-size:clamp(28px,4.2vw,44px);font-weight:600;line-height:1.05}
h2{font-size:22px;font-weight:600}
h3{font-size:17px;font-weight:600}
.mono{font-family:var(--f-mono);font-variant-numeric:tabular-nums}
.muted{color:var(--muted)}
.eyebrow{font:500 11px/1 var(--f-mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.head{display:grid;gap:14px;border-bottom:2px solid var(--ink);padding-bottom:18px}
.head-row{display:flex;flex-wrap:wrap;gap:12px 28px;align-items:end;justify-content:space-between}
.meta{display:flex;flex-wrap:wrap;gap:6px 22px;font:13px var(--f-mono);color:var(--muted)}
.meta b{color:var(--ink);font-weight:500}
.verdict{display:inline-flex;align-items:center;gap:10px;padding:8px 14px;border-radius:999px;font:600 14px var(--f-display);letter-spacing:.03em}
.verdict::before{content:"";width:9px;height:9px;border-radius:50%;background:currentColor}
.v-pass{background:var(--pass-bg);color:var(--pass)} .v-warn{background:var(--warn-bg);color:var(--warn)} .v-fail{background:var(--fail-bg);color:var(--fail)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--line);border:1px solid var(--line)}
.kpi{background:var(--panel);padding:14px 16px;display:grid;gap:4px}
.kpi .v{font:600 26px/1.1 var(--f-display);font-variant-numeric:tabular-nums}
.kpi .l{font-size:12px;color:var(--muted)}
.viewport{background:var(--viewport);border-radius:6px;overflow:hidden;line-height:0}
.viewport img{width:100%;height:auto;display:block}
.hero{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:14px}
.hero .side{display:grid;gap:14px;align-content:start}
@media (max-width:820px){.hero{grid-template-columns:1fr}}
section{display:grid;gap:14px}
.sec-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 16px;justify-content:space-between}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th{font:500 11px var(--f-mono);letter-spacing:.1em;text-transform:uppercase;color:var(--muted);text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
.num{text-align:right;white-space:nowrap}
.ledger tr.r-fail td:first-child{box-shadow:inset 3px 0 0 var(--fail)}
.ledger tr.r-warn td:first-child{box-shadow:inset 3px 0 0 var(--warn)}
.cname{font-weight:500}
.cdet{font-size:12.5px;color:var(--muted);max-width:62ch}
.chip{display:inline-block;padding:2px 9px;border-radius:999px;font:600 11.5px var(--f-mono);letter-spacing:.04em}
.s-pass{background:var(--pass-bg);color:var(--pass)} .s-warn{background:var(--warn-bg);color:var(--warn)}
.s-fail{background:var(--fail-bg);color:var(--fail)} .s-info{background:var(--info-bg);color:var(--info)}
.kind{font:500 11.5px var(--f-mono);padding:1px 7px;border:1px solid currentColor;border-radius:4px;white-space:nowrap}
.k-verified{color:var(--k-verified)} .k-measured{color:var(--k-measured)} .k-heuristic{color:var(--k-heuristic)} .k-estimated{color:var(--k-estimated)}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:12.5px;color:var(--muted)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend i{width:11px;height:11px;border-radius:2px;display:inline-block}
.sheet{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:18px;display:grid;gap:16px}
.sheet-head{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline;justify-content:space-between}
.two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
@media (max-width:760px){.two{grid-template-columns:1fr}}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px 18px}
.fact .l{font-size:12px;color:var(--muted)} .fact .v{font:500 15px var(--f-mono);font-variant-numeric:tabular-nums}
.curve{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:8px}
.curve img{width:100%;height:auto}
.gates{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.gate{border:1px solid var(--line);border-radius:6px;padding:14px;background:var(--panel);display:grid;gap:6px}
.gate.ok{border-color:var(--pass)} .gate .g{font:600 15px var(--f-display)}
.journal{list-style:none;margin:0;padding:0;display:grid;gap:0;border:1px solid var(--line);border-radius:6px;background:var(--panel)}
.journal li{display:grid;grid-template-columns:150px 110px minmax(0,1fr);gap:12px;padding:9px 14px;border-bottom:1px solid var(--line);font-size:13.5px}
.journal li:last-child{border-bottom:0}
.journal .jt{color:var(--muted);font-size:12px} .journal .jw{font:500 12px var(--f-mono);color:var(--accent)}
.journal li.j-human{background:var(--info-bg)} .journal li.j-human .jw{color:var(--info)}
@media (max-width:640px){.journal li{grid-template-columns:1fr}}
.callout{border-left:3px solid var(--warn);background:var(--warn-bg);padding:12px 16px;border-radius:0 6px 6px 0;font-size:14px}
.callout ul{margin:6px 0 0;padding-left:18px}
.assume{font-size:13px;color:var(--muted);margin:0;padding-left:18px}
details summary{cursor:pointer;color:var(--accent);font-size:13px}
details summary:focus-visible, a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
footer{font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:14px}
"""

LEGEND = [("#c9d3dc", "prints clean"), ("#5b6b7a", "on the plate"), ("#4cc9f0", "bridge"), ("#f4a261", "short overhang"),
          ("#ffd166", "steep overhang (rougher)"), ("#ef476f", "needs support")]


def write(proj: Project) -> Path:
    m = proj.manifest()
    spec = proj.spec
    R = {s: proj.result(s) for s in ["build", "orient", "check", "fit", "sim", "slice", "render"]}
    stale = {s: proj.stale(s) for s in R}
    files = (R["render"] or {}).get("files", {})

    rows = []
    for c in (R["build"] or {}).get("problems", []):
        rows.append(("build", "—", {"name": "Valid solids", "status": "fail", "kind": "verified", "detail": c}))
    for part, pr in ((R["check"] or {}).get("parts") or {}).items():
        rows += [("check", part, c) for c in pr["checks"]]
    rows += [("fit", "assembly", c) for c in (R["fit"] or {}).get("checks", [])]
    for case in (R["sim"] or {}).get("cases", []):
        rows += [("sim", case["part"], c) for c in case["checks"]]
    ph = proj.result("physics")
    if ph and not proj.stale("physics"):
        rows += [("physics", "mechanism", c) for c in ph.get("checks", [])]
    for part, pr in ((R["slice"] or {}).get("parts") or {}).items():
        rows += [("slice", part, c) for c in pr["checks"]]
    for s, why in stale.items():
        if why and s != "render" and not (s == "sim" and not m["design"]["loads"]):
            rows.insert(0, (s, "—", {"name": f"{s} result is current", "status": "fail", "kind": "verified",
                                      "detail": f"Stale: {why}. Re-run `forge run {proj.name}`."}))
    order = {"fail": 0, "warn": 1, "info": 2, "pass": 3}
    rows.sort(key=lambda r: order[r[2]["status"]])
    overall = worst([r[2] for r in rows])
    n_fail = sum(r[2]["status"] == "fail" for r in rows)
    n_warn = sum(r[2]["status"] == "warn" for r in rows)
    verdict = {"pass": ("v-pass", "Ready for print review"), "info": ("v-pass", "Ready for print review"),
               "warn": ("v-warn", f"Reviewable · {n_warn} warning{'s' * (n_warn != 1)}"),
               "fail": ("v-fail", f"Blocked · {n_fail} failing check{'s' * (n_fail != 1)}")}[overall]

    tot = (R["slice"] or {}).get("totals", {})
    sims = (R["sim"] or {}).get("cases", [])
    sfs = [c["eval"]["sf"] for c in sims if c["use"] == "static"]
    utils = [c["eval"].get("strain_util") for c in sims if c["use"] != "static"]
    kpis = [
        (str(len(m["parts"])), "parts"),
        (_hms(tot.get("time_s", 0)) if tot else "—", "print time (Bambu estimate)"),
        (f"{tot.get('filament_g', 0):.1f} g" if tot else "—", f"filament · {next(iter(m['parts'].values()))['material']}"),
        (f"{tot.get('cost', 0):.2f}" if tot else "—", "material cost (preset price)"),
        (f"{100 * tot.get('support_g', 0) / max(tot.get('filament_g', 1), 1e-9):.1f}%" if tot else "—", "support material"),
    ]
    if sfs:
        kpis.append((f"{min(sfs):.1f}×", "lowest safety factor"))
    if utils:
        kpis.append((f"{100 * max(utils):.0f}%", "peak flex strain vs allowable"))

    H = [f"<title>{html.escape(spec.get('title', proj.name))} Traveller</title>",
         '<meta name="claude:viewport-fit-sides" content="cover">',
         '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">',
         f"<style>{CSS}</style>", '<div class="wrap">']
    pr0 = next(iter(((R["check"] or {}).get("parts") or {}).values()), {}).get("printer", {})
    H.append(f"""<header class="head"><div class="eyebrow">Print traveller · forge {html.escape(m.get('project',''))}</div>
<div class="head-row"><h1>{html.escape(spec.get('title', proj.name))}</h1><span class="verdict {verdict[0]}">{verdict[1]}</span></div>
<p class="muted" style="margin:0;max-width:72ch">{html.escape(spec.get('summary', ''))}</p>
<div class="meta"><span>build <b>{m['build_hash'][:10]}</b></span><span>generated <b>{now()}</b></span>
<span>printer <b>{html.escape(pr0.get('machine', '—'))}</b></span><span>process <b>{html.escape(pr0.get('process', '—'))}</b></span>
<span>plate <b>{html.escape(pr0.get('bed_type', '—'))}</b></span></div></header>""")
    H.append('<div class="kpis">' + "".join(f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div></div>' for v, l in kpis) + "</div>")

    # hero
    side = []
    if files.get("motion"):
        side.append(f'<div class="viewport">{_img(proj, files["motion"], "Mechanism cycle")}</div>')
    if files.get("section"):
        side.append(f'<div class="viewport">{_img(proj, files["section"], "Cutaway")}</div>')
    if files.get("exploded"):
        side.append(f'<div class="viewport">{_img(proj, files["exploded"], "Exploded view")}</div>')
    if files.get("turntable") and not files.get("motion"):
        side.append(f'<div class="viewport">{_img(proj, files["turntable"], "Turntable")}</div>')
    H.append(f'<div class="hero"><div class="viewport">{_img(proj, files.get("hero"), "Assembly render")}</div><div class="side">{"".join(side)}</div></div>')

    # human attention
    attn = [f"<li><b>{html.escape(r[2]['name'])}</b> ({html.escape(r[1])}): {html.escape(r[2].get('detail') or '')}</li>"
            for r in rows if r[2]["status"] in ("fail", "warn")][:10]
    qs = [f"<li>{html.escape(q)}</li>" for q in spec.get("open_questions", [])]
    if attn or qs:
        H.append(f'<section><div class="sec-head"><h2>For your review</h2><span class="eyebrow">needs a human decision</span></div><div class="callout">'
                 + (f"<b>Flagged by checks</b><ul>{''.join(attn)}</ul>" if attn else "")
                 + (f"<b style='display:block;margin-top:8px'>Open design questions</b><ul>{''.join(qs)}</ul>" if qs else "")
                 + "<p style='margin:10px 0 0'>Aesthetics, feel and fit are your call: no check can judge them. Leave comments on this page or in the session.</p></div></section>")

    H.append(f'<section><div class="sec-head"><h2>Verification ledger</h2><span class="legend">'
             + "".join(f'<span>{_kind(k)} {v.lower()}</span>' for k, v in KIND_HELP.items())
             + f"</span></div>{_ledger(rows)}</section>")

    # parts
    H.append('<section><div class="sec-head"><h2>Parts on the plate</h2><span class="legend">'
             + "".join(f'<span><i style="background:{c}"></i>{l}</span>' for c, l in LEGEND) + "</span></div>")
    for part, meta in m["parts"].items():
        c = ((R["check"] or {}).get("parts") or {}).get(part, {})
        s = (((R["slice"] or {}).get("parts") or {}).get(part) or {}).get("stats", {})
        o = ((R["orient"] or {}).get("parts") or {}).get(part, {})
        ori = c.get("orientation", {})
        if c.get("purchased"):
            H.append(f"""<div class="sheet"><div class="sheet-head"><h3>{html.escape(part)}</h3><span class="chip s-info">Bought</span></div>
<p class="muted" style="margin:0">Purchased hardware: included in fits, motion and physics; not printed. {html.escape(meta.get('notes') or '')}</p></div>""")
            continue
        facts = [("orientation", f"{_fmt(ori.get('euler'))}°"), ("chosen by", ori.get("source", "—")),
                 ("volume", f"{meta['volume_mm3'] / 1000:.1f} cm³"), ("size", " × ".join(f"{x:g}" for x in meta["bbox_mm"]) + " mm"),
                 ("print time", s.get("time_str") or "—"), ("filament", f"{s.get('filament_g', 0):.1f} g" if s else "—"),
                 ("supports", "on" if s.get("support_enabled") else "off"), ("show faces", ", ".join(meta["cosmetic"]) or "none")]
        cand = o.get("candidates", [])[:5]
        ctab = ""
        if cand:
            ctab = ('<details><summary>Orientation candidates considered</summary><div class="scroll" style="margin-top:8px"><table><thead><tr><th>Pose</th><th class="num">Support mm²</th>'
                    '<th class="num">Height</th><th class="num">Bed contact mm²</th><th class="num">Min SF</th><th class="num">Score</th></tr></thead><tbody>'
                    + "".join(f'<tr><td>{html.escape(r["name"])}</td><td class="num mono">{r["support_mm2"]}</td><td class="num mono">{r["height_mm"]}</td>'
                              f'<td class="num mono">{r["contact_mm2"]}</td><td class="num mono">{r.get("sf_min", "—")}</td><td class="num mono">{r["score"]}</td></tr>' for r in cand)
                    + "</tbody></table></div><p class='muted' style='font-size:12.5px'>Lower score is better. Strength-aware: "
                    + ("yes, the FEA stress field was rotated into each pose." if o.get("strength_aware") else "no (no current simulation).") + "</p></details>")
        H.append(f"""<div class="sheet"><div class="sheet-head"><h3>{html.escape(part)}</h3>{_chip(c.get('status', 'info'))}</div>
<div class="facts">{''.join(f'<div class="fact"><div class="l">{k}</div><div class="v">{html.escape(str(v))}</div></div>' for k, v in facts)}</div>
<div class="two"><div class="viewport">{_img(proj, files.get(part + '_overhang'), part + ' overhang map')}</div>
<div class="viewport">{_img(proj, files.get(part + '_thickness'), part + ' wall thickness')}</div></div>{ctab}</div>""")
    H.append("</section>")

    # simulation
    if sims:
        H.append('<section><div class="sec-head"><h2>Load cases</h2><span class="eyebrow">CalculiX · quadratic tets</span></div>')
        for case in sims:
            ev, cv = case["eval"], case.get("convergence") or {}
            load = f"{_fmt(case['displacement'])} mm imposed" if case["displacement"] else f"{_fmt(case['force'])} N"
            facts = [("part", case["part"]), ("load", load), ("analysis", "large deflection" if case["nonlinear"] else "linear"),
                     ("use", case["use"]), ("reaction force", f"{abs(case['load_force_n']):.2f} N"),
                     ("max displacement", f"{case['disp_max_mm']:.3f} mm"),
                     ("peak von Mises", f"{ev['von_mises_max_mpa']:.1f} MPa"), ("tension across layers", f"{ev['interlayer_tension_max_mpa']:.1f} MPa"),
                     ("safety factor", f"{ev['sf']:.2f} ({ev['governing']})"), ("peak strain", f"{100 * ev['strain_max']:.2f}%"),
                     ("mesh", f"{case['mesh']['elements']} el · {case['mesh']['size_mm']} mm"),
                     ("convergence Δ", f"{cv.get('delta_peak_pct', '—')}%")]
            if "strain_util" in ev:
                facts.insert(6, ("strain vs allowable", f"{100 * ev['strain_util']:.0f}%"))
            H.append(f"""<div class="sheet"><div class="sheet-head"><h3>{html.escape(case['name'])}</h3>{''.join(_chip(c['status']) for c in case['checks'])}</div>
{f"<p class='muted' style='margin:0'>{html.escape(case['notes'])}</p>" if case.get('notes') else ''}
<div class="facts">{''.join(f'<div class="fact"><div class="l">{k}</div><div class="v">{html.escape(str(v))}</div></div>' for k, v in facts)}</div>
<div class="two"><div class="viewport">{_img(proj, files.get('fea_' + case['name']), 'FEA result')}</div>
<div class="curve">{_img(proj, files.get('curve_' + case['name']), 'Force-deflection curve') or "<p class='muted' style='padding:12px'>Linear case: single load step.</p>"}</div></div></div>""")
        H.append('<ul class="assume">' + "".join(f"<li>{html.escape(a)}</li>" for a in R["sim"]["assumptions"]) + "</ul></section>")

    # plates + gates
    plates = (R["slice"] or {}).get("plates", [])
    if plates:
        H.append('<section><div class="sec-head"><h2>Plates</h2><span class="eyebrow">Bambu Studio · headless</span></div><div class="scroll"><table><thead><tr><th>Plate</th><th>Parts</th>'
                 '<th>Material</th><th class="num">Time</th><th class="num">Filament</th><th class="num">Support</th><th>Status</th></tr></thead><tbody>'
                 + "".join(f'<tr><td class="mono">{html.escape(p["name"])}.3mf</td><td>{html.escape(", ".join(p["parts"]))}</td><td>{p["material"]}</td>'
                           f'<td class="num mono">{p["stats"].get("time_str", "—")}</td><td class="num mono">{p["stats"].get("filament_g", 0):.1f} g</td>'
                           f'<td class="num mono">{p["stats"].get("support_g", 0):.1f} g</td><td>{_chip(p["status"])}</td></tr>' for p in plates)
                 + "</tbody></table></div></section>")
    gs = gate.gate_status(proj)
    H.append('<section><div class="sec-head"><h2>Sign-off</h2><span class="eyebrow">approvals bind to a build hash</span></div><div class="gates">'
             + "".join(f'<div class="gate {"ok" if g["approved"] else ""}"><div class="eyebrow">{html.escape(k)}</div><div class="g">{"Approved" if g["approved"] else "Awaiting you"}</div>'
                       f'<div class="muted" style="font-size:13px">{html.escape(g["what"])}</div>'
                       f'<div class="mono muted" style="font-size:12px">{html.escape(g["detail"])}</div></div>' for k, g in gs.items())
             + "</div></section>")
    H.append(f'<section><div class="sec-head"><h2>Design journal</h2><span class="eyebrow">decisions and comments</span></div>{_journal_html(proj)}</section>')
    H.append(f'<footer>forge traveller for build {m["build_hash"][:10]}. Evidence kinds: '
             + "; ".join(f"{k}: {v.lower()}" for k, v in KIND_HELP.items())
             + f'. Fit clearances {"calibrated" if config.fits_calibrated() else "are uncalibrated defaults"}. Nothing is sent to the printer by forge.</footer></div>')
    out = proj.build_dir / "traveller.html"
    out.write_text("\n".join(H))
    summary = {"verdict": overall, "fails": n_fail, "warns": n_warn, "kpis": dict((l, v) for v, l in kpis),
               "rows": [{"stage": s, "part": p, **c} for s, p, c in rows], "stale": {k: v for k, v in stale.items() if v}}
    (proj.build_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    proj.save("report", {"status": overall, "path": str(out.relative_to(proj.dir)), "fails": n_fail, "warns": n_warn})
    return out
