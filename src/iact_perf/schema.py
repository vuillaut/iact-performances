"""Data model of the database: instruments, sources, records and Crab spectra.

Every YAML file and every ECSV record header is validated against these
models. Run ``python -m iact_perf.schema`` to regenerate the JSON Schema files
in ``schema/`` for non-Python tools.

Conventions:

- Physical values in metadata are strings parsed by astropy, e.g. ``"50 h"``.
- ``"unknown"`` means the source does not say. Never guess a value.
- ``None`` (absent key) means the field does not apply.
"""

from __future__ import annotations

import datetime
import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import astropy.units as u
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from . import units  # noqa: F401  (registers CU)

SCHEMA_VERSION = "0.2"

IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
SLUG_PART = r"[a-z0-9][a-z0-9.-]*"
SLUG_RE = re.compile(rf"^{SLUG_PART}_{SLUG_PART}_{SLUG_PART}$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")

Unknown = Literal["unknown"]


def _identifier(value: str) -> str:
    if not IDENTIFIER_RE.match(value):
        raise ValueError(f"{value!r} is not a valid identifier (lowercase, digits, '_', '.', '-')")
    return value


def _slug(value: str) -> str:
    if not SLUG_RE.match(value):
        raise ValueError(
            f"{value!r} is not a valid source slug: expected "
            "<instrument>_<firstauthor><year>_<topic>, lowercase ASCII"
        )
    return value


def _quantity_of(physical: u.UnitBase):
    def check(value: str) -> str:
        try:
            q = u.Quantity(value)
        except (TypeError, ValueError) as err:
            raise ValueError(f"{value!r} is not a quantity with a unit: {err}") from None
        if not q.unit.is_equivalent(physical):
            raise ValueError(f"{value!r} is not convertible to {physical}")
        return value

    return check


Identifier = Annotated[str, AfterValidator(_identifier)]
Slug = Annotated[str, AfterValidator(_slug)]
AngleStr = Annotated[str, AfterValidator(_quantity_of(u.deg))]
TimeStr = Annotated[str, AfterValidator(_quantity_of(u.h))]
EnergyStr = Annotated[str, AfterValidator(_quantity_of(u.TeV))]
LengthStr = Annotated[str, AfterValidator(_quantity_of(u.m))]
DiffFluxStr = Annotated[str, AfterValidator(_quantity_of(u.Unit("cm-2 s-1 TeV-1")))]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


# --------------------------------------------------------------------------- instruments


class InstrumentType(StrEnum):
    IACT = "IACT"
    WCD = "WCD"
    SPACE = "space"
    OTHER = "other"


class Mode(StrEnum):
    MONO = "mono"
    STEREO = "stereo"
    ARRAY = "array"
    OTHER = "other"


class Site(Model):
    name: str
    latitude: AngleStr | None = None
    longitude: AngleStr | None = None
    altitude: LengthStr | None = None


class Configuration(Model):
    """One way the instrument was operated: telescopes used, mode, period."""

    id: Identifier
    description: str
    mode: Mode
    n_telescopes: int | None = None
    period_start: str | None = Field(None, description="YYYY, YYYY-MM or YYYY-MM-DD")
    period_end: str | None = Field(
        None, description="YYYY, YYYY-MM or YYYY-MM-DD; absent if ongoing"
    )


class Instrument(Model):
    schema_version: str
    id: Identifier
    name: str
    type: InstrumentType
    site: Site | None = None
    configurations: list[Configuration] = Field(min_length=1)
    references: list[str] = Field(default_factory=list, description="DOIs or URLs")
    notes: str | None = None

    @model_validator(mode="after")
    def _unique_configurations(self):
        ids = [c.id for c in self.configurations]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate configuration ids in {self.id}: {ids}")
        return self

    def configuration(self, config_id: str) -> Configuration | None:
        """The configuration with this id, or None."""
        return next((c for c in self.configurations if c.id == config_id), None)


# --------------------------------------------------------------------------- sources


class SourceType(StrEnum):
    ARTICLE = "article"
    PROCEEDINGS = "proceedings"
    IRF_RELEASE = "irf_release"
    WEBPAGE = "webpage"
    THESIS = "thesis"
    REPORT = "report"


class Source(Model):
    """Content of ``sources/<slug>/source.yaml``."""

    schema_version: str
    title: str
    authors: list[str] = Field(min_length=1, description="Author list, may end with 'et al.'")
    year: int
    doi: str | None = Field(None, description="Publisher DOI preferred over the arXiv DOI")
    url: str | None = None
    accessed: datetime.date | None = Field(None, description="Required when there is no DOI")
    arxiv: str | None = None
    ads_bibcode: str | None = None
    source_type: SourceType
    refereed: bool
    instruments: list[Identifier] = Field(min_length=1)
    superseded_by: Slug | None = None
    reproducible: bool
    notes: str | None = None

    @model_validator(mode="after")
    def _identifier_present(self):
        if self.doi is None and self.url is None:
            raise ValueError("a source needs a doi or a url")
        if self.doi is not None and not DOI_RE.match(self.doi):
            raise ValueError(f"{self.doi!r} is not a DOI (expected 10.xxxx/...)")
        if self.doi is None and self.accessed is None:
            raise ValueError("a source identified by its url needs an 'accessed' date")
        if self.url is not None and not self.url.startswith(("http://", "https://")):
            raise ValueError(f"{self.url!r} is not an http(s) url")
        return self


# --------------------------------------------------------------------------- Crab spectra


class CrabSpectrum(Model):
    """A reference Crab spectrum, used to interpret values given in Crab units.

    Models (E0 = ``reference_energy``, A = ``amplitude``):

    - ``power_law``: A (E/E0)^-index
    - ``log_parabola_log10``: A (E/E0)^(-index - curvature log10(E/E0))
    - ``log_parabola_ln``: A (E/E0)^(-index - curvature ln(E/E0))
    - ``observed``: no analytic model. The Crab unit is the Crab flux observed
      in the same data set (e.g. a sensitivity computed on Crab observations);
      the values cannot be converted to an absolute flux.
    """

    id: Identifier
    description: str
    reference: str = Field(description="DOI or URL of the publication of the fit or data")
    model: Literal["power_law", "log_parabola_log10", "log_parabola_ln", "observed"]
    amplitude: DiffFluxStr | None = None
    reference_energy: EnergyStr | None = None
    index: float | None = None
    curvature: float | None = None
    energy_range: tuple[EnergyStr, EnergyStr] | None = None

    @property
    def is_model(self) -> bool:
        """False for an ``observed`` reference, which has no spectral model."""
        return self.model != "observed"

    @model_validator(mode="after")
    def _parameters(self):
        params = (self.amplitude, self.reference_energy, self.index)
        if not self.is_model:
            if any(p is not None for p in (*params, self.curvature)):
                raise ValueError("an 'observed' Crab reference has no spectral parameters")
            return self
        if any(p is None for p in params):
            raise ValueError("'amplitude', 'reference_energy' and 'index' are required")
        if (self.model == "power_law") != (self.curvature is None):
            raise ValueError("'curvature' is required for log-parabolas and forbidden otherwise")
        return self


class Analysis(Model):
    """An analysis chain or production, shared by all the records it produced.

    Records are queried by instrument and by analysis: e.g. ``freepact``,
    ``prod5-official``, ``magic-mars-standard``. Use one id per analysis that
    a user would want to select or compare, not one per paper.
    """

    id: Identifier
    name: str
    description: str
    references: list[str] = Field(default_factory=list, description="DOIs or URLs")


class Analyses(Model):
    """Content of ``references/analyses.yaml``."""

    schema_version: str
    analyses: list[Analysis]

    @model_validator(mode="after")
    def _unique(self):
        ids = [a.id for a in self.analyses]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate analysis ids: {ids}")
        return self


class CrabSpectra(Model):
    """Content of ``references/crab_spectra.yaml``."""

    schema_version: str
    spectra: list[CrabSpectrum]


# --------------------------------------------------------------------------- records


class PerformanceQuantity(StrEnum):
    SENSITIVITY = "sensitivity"
    ANGULAR_RESOLUTION = "angular_resolution"
    ENERGY_RESOLUTION = "energy_resolution"
    ENERGY_BIAS = "energy_bias"
    EFFECTIVE_AREA = "effective_area"
    BACKGROUND_RATE = "background_rate"
    GAMMA_RATE = "gamma_rate"
    ENERGY_THRESHOLD = "energy_threshold"
    FIELD_OF_VIEW = "field_of_view"


#: Allowed ``definition`` values. A quantity listed here requires a definition.
DEFINITIONS: dict[str, set[str]] = {
    "angular_resolution": {"containment_68", "containment_80", "gaussian_sigma", "other"},
    "energy_resolution": {"gaussian_sigma", "rms", "containment_68", "other"},
    "energy_bias": {"gaussian_mean", "mean", "median", "other"},
    "effective_area": {"no_direction_cut", "direction_cut", "other"},
}

#: Quantities that are a single value, not a curve versus energy.
SCALAR_QUANTITIES = {"energy_threshold", "field_of_view"}

#: Quantities for which ``energy_integration`` is required.
INTEGRATED_QUANTITIES = {"sensitivity", "background_rate", "gamma_rate"}

#: Units the ``value`` column of each quantity must be convertible to (any of them).
VALUE_UNITS: dict[str, list[u.UnitBase]] = {
    "sensitivity": [
        units.CU,
        u.Unit("cm-2 s-1"),
        u.Unit("cm-2 s-1 TeV-1"),
        u.Unit("erg cm-2 s-1"),
    ],
    "angular_resolution": [u.deg],
    "energy_resolution": [u.dimensionless_unscaled],
    "energy_bias": [u.dimensionless_unscaled],
    "effective_area": [u.m**2],
    "background_rate": [
        u.Unit("s-1"),
        u.Unit("s-1 sr-1"),
        u.Unit("s-1 TeV-1"),
        u.Unit("s-1 sr-1 TeV-1"),
    ],
    "gamma_rate": [u.Unit("s-1"), u.Unit("s-1 TeV-1")],
    "energy_threshold": [u.TeV],
    "field_of_view": [u.deg, u.sr],
}


class SensitivityCriteria(Model):
    """How a sensitivity was defined. All of these change the curve."""

    significance: float = Field(description="Required significance, in sigma")
    significance_formula: Literal["excess_over_sqrt_background", "li_ma_eq17", "other", "unknown"]
    n_off_regions: int | Unknown | None = Field(None, description="Absent if not applicable")
    min_excess: float | Literal["none", "unknown"] = Field(
        description="Minimum number of excess events, 'none' if no such condition"
    )
    min_signal_to_background: float | Literal["none", "unknown"] = Field(
        description="Minimum excess / background ratio (0.05 for 5 %), 'none' if no condition"
    )
    bins_per_decade: float | Unknown | None = Field(
        None, description="Energy bins per decade, differential sensitivity only"
    )


class Conditions(Model):
    """Observation and analysis conditions. ``unknown`` when the source does not say."""

    zenith_range: tuple[AngleStr, AngleStr] | Unknown = "unknown"
    azimuth: str | Unknown = "unknown"
    offset: AngleStr | Unknown = "unknown"
    moon: Literal["dark", "moderate", "high", "any", "unknown"] = "unknown"
    analysis_details: str | Unknown = Field(
        "unknown", description="Software, algorithms and settings, in words"
    )
    cuts: str | Unknown = "unknown"


class Provenance(Model):
    method: Literal[
        "latex_table", "pdf_table", "vector_figure", "raster_digitized", "official_data_file"
    ]
    location: str = Field(description="Where in the source, e.g. 'Table A7 (tab:diffsens)'")
    original_column: str | None = None
    digitization_uncertainty: str | None = None


class RecordMeta(Model):
    """Header of one record (one value or curve of one quantity from one source).

    Stored in the ECSV ``meta`` under the key ``iact_perf``. The columns of the
    table are checked by :func:`iact_perf.records.check_columns`.
    """

    schema_version: str
    label: str = Field(description="Short human-readable description")
    quantity: PerformanceQuantity
    definition: str | None = None
    energy_integration: Literal["differential", "integral"] | None = None
    energy_type: Literal["true", "reconstructed", "unknown"] | None = None
    instrument: Identifier
    configuration: Identifier
    analysis: Identifier = Field(
        description="Analysis or production that made the curve, from references/analyses.yaml"
    )
    data_kind: Literal["monte_carlo", "real_data", "mixed"]
    observation_time: TimeStr | None = Field(
        None,
        description=(
            "Observation time of a sensitivity; for IRF productions, also the time "
            "the analysis cuts were optimised for, on every quantity"
        ),
    )
    sensitivity_criteria: SensitivityCriteria | None = None
    crab_reference: Identifier | None = Field(None, description="Required for values in CU")
    conditions: Conditions = Field(default_factory=Conditions)
    provenance: Provenance
    notes: str | None = None

    @model_validator(mode="after")
    def _consistency(self):
        q = self.quantity
        if q in DEFINITIONS:
            if self.definition is None:
                raise ValueError(f"{q} needs a 'definition' among {sorted(DEFINITIONS[q])}")
            if self.definition not in DEFINITIONS[q]:
                raise ValueError(
                    f"definition {self.definition!r} not allowed for {q}: {sorted(DEFINITIONS[q])}"
                )
        if q in INTEGRATED_QUANTITIES and self.energy_integration is None:
            raise ValueError(f"{q} needs 'energy_integration' (differential or integral)")
        if q not in SCALAR_QUANTITIES and self.energy_type is None:
            raise ValueError(f"{q} is a curve versus energy and needs 'energy_type'")
        if q == "sensitivity":
            if self.observation_time is None:
                raise ValueError("a sensitivity needs 'observation_time'")
            if self.sensitivity_criteria is None:
                raise ValueError("a sensitivity needs 'sensitivity_criteria'")
            bins = self.sensitivity_criteria.bins_per_decade
            if self.energy_integration == "differential" and bins is None:
                raise ValueError("a differential sensitivity needs 'bins_per_decade'")
            if self.energy_integration == "integral" and bins is not None:
                raise ValueError("'bins_per_decade' does not apply to an integral sensitivity")
        elif self.sensitivity_criteria is not None:
            raise ValueError("'sensitivity_criteria' only applies to sensitivities")
        return self


# --------------------------------------------------------------------------- JSON Schema

MODELS = {
    "instrument": Instrument,
    "source": Source,
    "record": RecordMeta,
    "crab_spectra": CrabSpectra,
    "analyses": Analyses,
}


def write_json_schemas(directory: Path) -> list[Path]:
    """Write one JSON Schema file per model into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, model in MODELS.items():
        path = directory / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
        paths.append(path)
    return paths
