"""Human gates and print release.

Gates
  spec     the requirements, loads and fits are right.     Binds to spec.yaml minus params/printer.
  concept  this design direction is the one to detail.     Approved once.
  print    this exact build may be printed.               Binds to the build hash.

`forge approve` only runs from an interactive terminal and asks you to type the
project name. Agent shells have no TTY, so this stops an agent approving by accident.
It is a guard rail, not a security boundary: anything with file access could edit
approvals.json. docs/claude-settings.proposed.json adds deny rules if you install it.

`forge release` copies the sliced 3MF plates to release/ only when every stage is
current, nothing fails, and the print gate was approved for this build hash.
It never sends anything to a printer."""
from __future__ import annotations

import getpass
import json
import shutil
import sys

from .config import ForgeError
from .project import Project, now, sha

GATES = {
    "spec": "Requirements, loads, fits and show faces are right (optional record)",
    "concept": "This design direction is the one to detail (optional record)",
    "print": "This exact build may be printed",
}


def _approvals(proj: Project) -> list[dict]:
    p = proj.dir / "approvals.json"
    return json.loads(p.read_text()) if p.exists() else []


def spec_hash(proj: Project) -> str:
    """The spec gate approves REQUIREMENTS (user decision, 2026-11-15): it hashes everything in
    spec.yaml except `params` and `printer`, which detail design is expected to tune. Dimension
    changes are still reviewed at the print gate, which binds to the exact build."""
    import json as _json
    spec = dict(proj.spec)
    for k in ("params", "printer"):
        spec.pop(k, None)
    return sha(_json.dumps(spec, sort_keys=True, default=str).encode())


def gate_status(proj: Project) -> dict:
    ap = _approvals(proj)
    try:
        bh = proj.manifest()["build_hash"]
    except ForgeError:
        bh = None
    sh = spec_hash(proj)
    out = {}
    for g, what in GATES.items():
        mine = [a for a in ap if a["gate"] == g]
        last = mine[-1] if mine else None
        if not last:
            ok, det = False, "not approved"
        elif g == "spec":
            ok = last["spec_hash"] == sh
            det = f"by {last['by']} {last['at']}" if ok else "spec.yaml changed since approval"
        elif g == "print":
            ok = last["build_hash"] == bh
            det = f"by {last['by']} {last['at']} · build {last['build_hash'][:10]}" if ok else f"approved build {last['build_hash'][:10]}, current is {(bh or '?')[:10]}"
        else:
            ok, det = True, f"by {last['by']} {last['at']}"
        out[g] = {"approved": ok, "what": what, "detail": det, "note": (last or {}).get("note", "")}
    return out


def blockers(proj: Project, for_gate: str = "print") -> list[str]:
    out = []
    stages = ["build", "check", "fit", "slice", "report"]
    if proj.manifest()["design"]["loads"]:
        stages.insert(3, "sim")
    for s in stages:
        why = proj.stale(s)
        if why:
            out.append(f"{s}: {why}")
            continue
        r = proj.result(s)
        if r.get("status") == "fail":
            out.append(f"{s}: has failing checks")
    gs = gate_status(proj)
    # User decision (2026-11-15, "i'd like to have less stuff to approve"): only the PRINT gate is
    # mandatory. Spec and concept decisions are made in chat and logged in the journal; formal
    # `forge approve <p> spec|concept` records are optional and never block.
    return out


def approve(proj: Project, gate: str, note: str = "") -> dict:
    if gate not in GATES:
        raise ForgeError(f"Unknown gate {gate!r}; one of {list(GATES)}")
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ForgeError("`forge approve` must be run by a person in an interactive terminal. Agents cannot approve gates.")
    m = proj.manifest() if (proj.build_dir / "manifest.json").exists() else {"build_hash": "-"}
    if gate == "print":
        b = blockers(proj)
        if b:
            raise ForgeError("Cannot approve print while blocked:\n  - " + "\n  - ".join(b))
    print(f"\nApproving gate '{gate}' for project '{proj.name}': {GATES[gate]}")
    if gate == "print":
        print(f"Build {m['build_hash'][:10]}. Review build/traveller.html first.")
    typed = input(f"Type the project name ({proj.name}) to approve: ").strip()
    if typed != proj.name:
        raise ForgeError("Not approved (name did not match).")
    if not note:
        note = input("Note (optional): ").strip()
    rec = {"gate": gate, "by": getpass.getuser(), "at": now(), "build_hash": m["build_hash"],
           "spec_hash": spec_hash(proj), "note": note}
    ap = _approvals(proj)
    ap.append(rec)
    (proj.dir / "approvals.json").write_text(json.dumps(ap, indent=2))
    proj.journal(f"approved gate **{gate}**" + (f": {note}" if note else ""), author="human", kind="gate")
    return rec


def release(proj: Project) -> list[str]:
    b = blockers(proj)
    if not gate_status(proj)["print"]["approved"]:
        b.append("gate 'print' not approved for this build. Run `forge approve " + proj.name + " print` yourself.")
    if b:
        raise ForgeError("Release blocked:\n  - " + "\n  - ".join(b))
    m = proj.manifest()
    out = proj.dir / "release"
    out.mkdir(exist_ok=True)
    files = []
    for p in proj.result("slice")["plates"]:
        src = proj.dir / p["threemf"]
        dst = out / f"{p['name']}-{m['build_hash'][:8]}.3mf"
        shutil.copy(src, dst)
        files.append(str(dst))
    shutil.copy(proj.build_dir / "traveller.html", out / f"traveller-{m['build_hash'][:8]}.html")
    proj.journal(f"released build {m['build_hash'][:10]}: {', '.join(f.split('/')[-1] for f in files)}", author="forge", kind="gate")
    return files
