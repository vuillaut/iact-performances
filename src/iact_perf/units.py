"""Units that astropy does not provide.

``CU`` is the Crab unit: a flux expressed as a fraction of the Crab Nebula
flux. It is an irreducible unit on purpose: converting it to an absolute flux
needs the reference Crab spectrum of the record (``crab_reference``), so
astropy must never do it silently. A sensitivity published in "% C.U." is
stored with the unit ``% CU``.
"""

import astropy.units as u

CU = u.def_unit(["CU", "crab_unit"], doc="Crab unit: flux relative to a reference Crab spectrum")

u.add_enabled_units([CU])


def is_crab_unit(unit: u.UnitBase) -> bool:
    """True if ``unit`` is a multiple of the Crab unit (CU, % CU, ...)."""
    return unit.is_equivalent(CU)
