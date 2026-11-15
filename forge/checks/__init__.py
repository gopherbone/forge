"""Check helpers. Every check returns a dict:
{id, name, status: pass|warn|fail|info, kind: verified|measured|heuristic|estimated, value, limit, detail}
  verified  - exact geometric / slicer fact
  measured  - sampled measurement of the real geometry (can miss tiny spots)
  heuristic - rule of thumb about how prints behave
  estimated - simulation or material-data based; only as good as its inputs
"""


def check(id, name, status, kind, value=None, limit=None, detail=""):
    return {"id": id, "name": name, "status": status, "kind": kind, "value": value, "limit": limit, "detail": detail}


def worst(checks):
    order = {"fail": 3, "warn": 2, "info": 1, "pass": 0}
    return max((c["status"] for c in checks), key=lambda s: order[s], default="pass")
