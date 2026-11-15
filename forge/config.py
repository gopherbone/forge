"""Paths, external tools, and data files. Nothing here is guessed silently:
anything not found raises with a fix-it message."""
from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent
PROJECTS = ROOT / "projects"
DATA = PKG / "data"
TOOLS = ROOT / ".tools"

BAMBU_APP = Path(os.environ.get("FORGE_BAMBU", "/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"))
BAMBU_SYSTEM = Path.home() / "Library/Application Support/BambuStudio/system/BBL"
BAMBU_USER = Path.home() / "Library/Application Support/BambuStudio/user"


class ForgeError(RuntimeError):
    pass


def ccx_path() -> Path:
    """CalculiX. FreeCAD.app ships ccx but its libgfortran rpath is broken on macOS;
    `make tools` copies it to .tools/bin with the rpath fixed (FreeCAD.app untouched)."""
    for cand in [os.environ.get("FORGE_CCX"), TOOLS / "bin/ccx", shutil.which("ccx")]:
        if cand and Path(cand).exists():
            return Path(cand)
    raise ForgeError("CalculiX (ccx) not found. Run `make tools` (needs FreeCAD.app + `brew install gcc`).")


def bambu_path() -> Path:
    if not BAMBU_APP.exists():
        raise ForgeError(f"Bambu Studio not found at {BAMBU_APP}. Set FORGE_BAMBU.")
    return BAMBU_APP


@lru_cache
def load_yaml(name: str) -> dict:
    return yaml.safe_load((DATA / name).read_text())


def materials() -> dict:
    return load_yaml("materials.yaml")["materials"]


def material(name: str) -> dict:
    m = materials()
    if name not in m:
        raise ForgeError(f"Unknown material {name!r}. Known: {', '.join(m)} (edit forge/data/materials.yaml)")
    return m[name]


def fits_table() -> dict:
    """Fit clearances. Project-local calibration (projects/_calibration/fits.yaml) wins."""
    base = load_yaml("fits.yaml")
    cal = PROJECTS / "_calibration" / "fits.yaml"
    if cal.exists():
        override = yaml.safe_load(cal.read_text()) or {}
        for k, v in (override.get("fits") or {}).items():
            base["fits"].setdefault(k, {}).update(v)
    return base["fits"]


def rules() -> dict:
    return load_yaml("rules.yaml")


def fits_calibrated() -> bool:
    return (PROJECTS / "_calibration" / "fits.yaml").exists()
