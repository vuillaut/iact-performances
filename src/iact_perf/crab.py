"""Reference Crab spectra and conversions between Crab units and absolute fluxes.

Conventions, which match how performance papers usually convert:

- differential values in CU are relative to the Crab dN/dE at the energy of
  the point (the geometric bin centre when only the bin edges are given);
- integral values in CU are relative to the integral Crab flux above the
  threshold energy.
"""

from __future__ import annotations

import astropy.units as u
import numpy as np

from .schema import CrabSpectrum
from .units import CU, is_crab_unit

DIFF_FLUX = u.Unit("cm-2 s-1 TeV-1")
INT_FLUX = u.Unit("cm-2 s-1")
ENERGY_FLUX = u.Unit("erg cm-2 s-1")

#: Upper bound of the integral Crab flux above a threshold.
INTEGRAL_EMAX = 1000 * u.TeV


def dnde(spectrum: CrabSpectrum, energy: u.Quantity) -> u.Quantity:
    """Differential Crab flux at ``energy``, in cm-2 s-1 TeV-1."""
    a = u.Quantity(spectrum.amplitude).to(DIFF_FLUX)
    x = (u.Quantity(energy) / u.Quantity(spectrum.reference_energy)).to_value(u.one)
    if spectrum.model == "power_law":
        exponent = -spectrum.index
    elif spectrum.model == "log_parabola_log10":
        exponent = -spectrum.index - spectrum.curvature * np.log10(x)
    else:  # log_parabola_ln
        exponent = -spectrum.index - spectrum.curvature * np.log(x)
    return a * x**exponent


def integral_flux(spectrum: CrabSpectrum, threshold: u.Quantity, n: int = 2000) -> u.Quantity:
    """Integral Crab flux above ``threshold`` (up to 1000 TeV), in cm-2 s-1."""
    threshold = np.atleast_1d(u.Quantity(threshold).to_value(u.TeV))
    out = []
    for e0 in threshold:
        e = np.geomspace(e0, INTEGRAL_EMAX.to_value(u.TeV), n)
        f = dnde(spectrum, e * u.TeV).to_value(DIFF_FLUX)
        out.append(np.trapezoid(f * e, np.log(e)))  # integrate in log E for accuracy
    return np.array(out) * INT_FLUX


def convert(
    value: u.Quantity,
    unit: u.UnitBase | str,
    energy: u.Quantity,
    integration: str,
    spectrum: CrabSpectrum | None = None,
) -> u.Quantity:
    """Convert sensitivity values between Crab units, fluxes and energy fluxes.

    ``integration`` is ``"differential"`` (CU, cm-2 s-1 TeV-1, erg cm-2 s-1)
    or ``"integral"`` (CU, cm-2 s-1). ``spectrum`` is needed when CU is on
    either side.
    """
    value = u.Quantity(value)
    unit = u.Unit(unit)
    if value.unit.is_equivalent(unit):
        return value.to(unit)
    energy = u.Quantity(energy)
    needs_crab = is_crab_unit(value.unit) or is_crab_unit(unit)
    if needs_crab and spectrum is None:
        raise ValueError("converting Crab units needs a reference Crab spectrum")

    if integration == "differential":
        if is_crab_unit(value.unit):
            base = value.to_value(CU) * dnde(spectrum, energy)
        elif value.unit.is_equivalent(DIFF_FLUX):
            base = value.to(DIFF_FLUX)
        elif value.unit.is_equivalent(ENERGY_FLUX):
            base = (value / energy**2).to(DIFF_FLUX)
        else:
            raise u.UnitConversionError(f"cannot convert {value.unit} as a differential flux")
        if is_crab_unit(unit):
            return (base / dnde(spectrum, energy)).to_value(u.one) * CU.to(unit) * unit
        if unit.is_equivalent(DIFF_FLUX):
            return base.to(unit)
        if unit.is_equivalent(ENERGY_FLUX):
            return (base * energy**2).to(unit)
        raise u.UnitConversionError(f"cannot convert a differential flux to {unit}")

    if integration == "integral":
        if is_crab_unit(value.unit):
            base = value.to_value(CU) * integral_flux(spectrum, energy)
        elif value.unit.is_equivalent(INT_FLUX):
            base = value.to(INT_FLUX)
        else:
            raise u.UnitConversionError(f"cannot convert {value.unit} as an integral flux")
        if is_crab_unit(unit):
            return (base / integral_flux(spectrum, energy)).to_value(u.one) * CU.to(unit) * unit
        if unit.is_equivalent(INT_FLUX):
            return base.to(unit)
        raise u.UnitConversionError(f"cannot convert an integral flux to {unit}")

    raise ValueError(f"integration must be 'differential' or 'integral', not {integration!r}")
