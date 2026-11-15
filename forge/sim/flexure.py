"""Closed-form sizing for flexures, used at the concept stage before FEA.
These are small-deflection beam formulas: good for sizing, then FEA confirms.

    forge flex cantilever --L 12 --t 1.6 --b 6 --y 0.9 --material PETG
"""
from __future__ import annotations

from .. import config


def cantilever_snap(L: float, t: float, b: float, y: float, material: str = "PETG", taper: float = 1.0,
                    mu: float = 0.3, angle_deg: float = 30.0, use: str = "once") -> dict:
    """Straight cantilever snap hook of length L, thickness t (deflection direction), width b,
    deflected y at the tip. taper = tip/root thickness (1 = constant; 0.5 lowers root strain ~ 0.6x).
    Returns peak strain, tip force, and the push-on force for a lead-in of angle_deg."""
    import math
    m = config.material(material)
    k = {1.0: 1.5, 0.75: 1.2, 0.5: 0.92}.get(round(taper, 2), 1.5 * (0.35 + 0.65 * taper))
    eps = k * y * t / L ** 2
    E = m["E_mpa"]
    P = b * t ** 2 * E * eps / (6 * L)  # force to deflect the tip
    a = math.radians(angle_deg)
    W = P * (mu + math.tan(a)) / (1 - mu * math.tan(a))  # assembly (mating) force
    allow = m["strain_allow_once" if use == "once" else "strain_allow_repeated"]
    return {"strain": round(eps, 5), "strain_allow": allow, "util": round(eps / allow, 3), "tip_force_n": round(P, 2),
            "push_force_n": round(W, 2), "max_deflection_mm": round(allow * L ** 2 / (k * t), 3),
            "note": "Small-deflection beam theory. Confirm with a nonlinear LoadCase."}


def living_hinge(L: float, t: float, angle_deg: float, material: str = "PETG", use: str = "repeated") -> dict:
    """Thin strip of length L, thickness t bent to angle_deg as a uniform arc:
    strain = t / (2R), R = L / theta. FDM living hinges should be printed with the
    hinge length along the layers (strip in XY), never across them."""
    import math
    m = config.material(material)
    th = math.radians(angle_deg)
    eps = t * th / (2 * L)
    allow = m["strain_allow_once" if use == "once" else "strain_allow_repeated"]
    return {"strain": round(eps, 5), "strain_allow": allow, "util": round(eps / allow, 3),
            "min_length_mm": round(t * th / (2 * allow), 2),
            "note": "Uniform-curvature estimate. PETG hinges last far longer than PLA but far less than PP."}
