"""forge — a verifiable design-for-print pipeline for the Bambu Lab X1C.

Every stage writes a JSON result stamped with the geometry hash it was computed
from, so a stale result can never satisfy a release gate.
"""
__version__ = "0.1.0"
