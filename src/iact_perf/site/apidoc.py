"""Generate the API reference page from the signatures and docstrings of the library.

The page is rebuilt with the site, so it cannot drift from the code. Docstrings
use reStructuredText inline markup (``code``, :func:`name`); it is turned into
Markdown here. Pydantic models are shown as a table of their fields.
"""

from __future__ import annotations

import dataclasses
import enum
import importlib
import inspect
import re
import typing

from pydantic import BaseModel

#: Sections of the page: (title, introduction, objects as "module:qualname").
SECTIONS = [
    (
        "Loading and querying",
        "Start here: `iact_perf.load()` returns a `Database`.",
        ["iact_perf.database:load", "iact_perf.database:Database"],
    ),
    (
        "Records",
        "A record is one value or curve of one quantity, from one source.",
        [
            "iact_perf.records:Record",
            "iact_perf.records:read_record",
            "iact_perf.records:write_record",
            "iact_perf.records:check_columns",
        ],
    ),
    (
        "Crab units",
        "Conversions between Crab units, fluxes and energy fluxes. "
        "`Database.convert` calls them with the record's Crab spectrum.",
        [
            "iact_perf.units:is_crab_unit",
            "iact_perf.crab:dnde",
            "iact_perf.crab:integral_flux",
            "iact_perf.crab:convert",
            "iact_perf.crab:NoCrabModel",
        ],
    ),
    (
        "Record header",
        "The metadata of a record, `Record.meta`. Values are strings with a unit "
        '(`"50 h"`); `"unknown"` means the source does not say.',
        [
            "iact_perf.schema:RecordMeta",
            "iact_perf.schema:Conditions",
            "iact_perf.schema:SensitivityCriteria",
            "iact_perf.schema:Provenance",
        ],
    ),
    (
        "Sources, instruments and references",
        "`Database.sources`, `Database.instruments`, `Database.analyses` and "
        "`Database.crab_spectra` hold these objects.",
        [
            "iact_perf.schema:Source",
            "iact_perf.schema:Instrument",
            "iact_perf.schema:Configuration",
            "iact_perf.schema:Site",
            "iact_perf.schema:Analysis",
            "iact_perf.schema:CrabSpectrum",
        ],
    ),
    (
        "Validation",
        "For contributors: the checks run by `iact-perf validate`.",
        ["iact_perf.catalog:validate_repository", "iact_perf.catalog:default_root"],
    ),
]

_ROLE = re.compile(r":(?:py:)?(?:func|mod|class|meth|attr|data|obj):`~?([^`]+)`")


def _md(text: str) -> str:
    """reST inline markup and doctest examples to Markdown."""
    text = _ROLE.sub(r"`\1`", text)
    text = re.sub(r"``([^`]+)``", r"`\1`", text)
    out, in_code = [], False
    for line in text.splitlines():
        is_code = line.startswith((">>> ", "... "))
        if is_code and not in_code:
            out.append("```python")
        elif not is_code and in_code:
            out.append("```")
        in_code = is_code
        out.append(line[4:] if is_code else line)
    if in_code:
        out.append("```")
    return "\n".join(out)


def _doc(obj) -> str:
    # a class without its own docstring would show the one of its base (pydantic's)
    own = obj.__dict__.get("__doc__") if inspect.isclass(obj) else obj.__doc__
    return _md(inspect.cleandoc(own)) if own else ""


_PREFIXES = re.compile(
    r"\b(?:iact_perf\.(?:schema|records|database)\.|astropy\.table\.table\.|"
    r"pathlib\.|typing\.|collections\.abc\.)"
)


def _clean(text: str) -> str:
    """Shorter type names: ``Instrument`` for ``iact_perf.schema.Instrument``."""
    return _PREFIXES.sub("", text).replace("astropy.units.core.", "u.")


def _annotation(a) -> str:
    if a is inspect.Parameter.empty:
        return ""
    return _clean(a if isinstance(a, str) else inspect.formatannotation(a))


def _signature(name: str, func) -> str:
    sig = inspect.signature(func)
    parts, star_done = [], False
    for p in sig.parameters.values():
        if p.name == "self":
            continue
        if p.kind is p.KEYWORD_ONLY and not star_done:
            parts.append("*")
            star_done = True
        if p.kind is p.VAR_KEYWORD:
            parts.append(f"**{p.name}")
            continue
        if p.kind is p.VAR_POSITIONAL:
            parts.append(f"*{p.name}")
            star_done = True
            continue
        text = p.name
        ann = _annotation(p.annotation)
        if ann:
            text += f": {ann}"
        if p.default is not p.empty:
            text += f" = {p.default!r}" if ann else f"={p.default!r}"
        parts.append(text)
    ret = _annotation(sig.return_annotation)
    one_line = f"{name}({', '.join(parts)})" + (f" -> {ret}" if ret else "")
    if len(one_line) <= 88:
        return one_line
    body = "".join(f"\n    {p}," for p in parts)
    return f"{name}({body}\n)" + (f" -> {ret}" if ret else "")


def _code(text: str) -> str:
    return f"```python\n{text}\n```\n"


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _field_type(field) -> str:
    a = field.annotation
    if inspect.isclass(a) and issubclass(a, enum.Enum):
        return " | ".join(repr(m.value) for m in a)
    text = inspect.formatannotation(a) if not isinstance(a, str) else a
    # Annotated[str, AfterValidator(...)] -> str; Literal['a', 'b'] -> 'a' | 'b'
    text = re.sub(r"Annotated\[(\w+), [^\]]*\]", r"\1", text)
    text = re.sub(r"Literal\[([^\]]*)\]", lambda m: m.group(1).replace(", ", " | "), text)
    return _clean(text)


def _model(name: str, model: type[BaseModel]) -> str:
    rows = []
    for fname, field in model.model_fields.items():
        if field.is_required():
            default = "required"
        elif field.default_factory is not None:
            default = "empty"
        else:
            default = f"`{field.default!r}`"
        rows.append(
            f"| `{fname}` | `{_cell(_field_type(field))}` | {default} | "
            f"{_cell(field.description or '')} |"
        )
    doc = _doc(model)
    out = [f"### `{name}`\n"] + ([doc + "\n"] if doc else [])
    out.append("| Field | Type | Default | Description |\n|---|---|---|---|\n" + "\n".join(rows))
    out.append("")
    out += _methods(name, model, skip=set(dir(BaseModel)))
    return "\n".join(out)


def _methods(owner: str, cls, skip=frozenset()) -> list[str]:
    out = []
    for attr, value in cls.__dict__.items():
        if attr.startswith("_") or attr in skip:
            continue
        if isinstance(value, property):
            doc = _doc(value) or ""
            out.append(f"#### `{owner}.{attr}` (property)\n\n{doc}\n")
        elif inspect.isfunction(value):
            out.append(
                f"#### `{owner}.{attr}`\n\n{_code(_signature(attr, value))}\n{_doc(value)}\n"
            )
    return out


def _dataclass(name: str, cls) -> str:
    out = [f"### `{name}`\n", _doc(cls) + "\n"]
    hints = typing.get_type_hints(cls, include_extras=False, localns=vars(inspect.getmodule(cls)))
    rows = [
        f"| `{f.name}` | `{_cell(_clean(inspect.formatannotation(hints[f.name])))}` |"
        for f in dataclasses.fields(cls)
    ]
    out.append("| Attribute | Type |\n|---|---|\n" + "\n".join(rows) + "\n")
    out += _methods(name, cls)
    return "\n".join(out)


def _object(path: str) -> str:
    module_name, qualname = path.split(":")
    obj = getattr(importlib.import_module(module_name), qualname)
    # the shortest import path: iact_perf.load rather than iact_perf.database.load
    top = importlib.import_module("iact_perf")
    public = f"iact_perf.{qualname}" if getattr(top, qualname, None) is obj else path
    footer = f"\nImport: `{public.replace(':', '.')}`\n"
    if inspect.isclass(obj) and issubclass(obj, BaseModel):
        return _model(qualname, obj) + footer
    if dataclasses.is_dataclass(obj):
        return _dataclass(qualname, obj) + footer
    if inspect.isclass(obj):
        return f"### `{qualname}`\n\n{_doc(obj)}\n" + footer
    return f"### `{qualname}`\n\n{_code(_signature(qualname, obj))}\n{_doc(obj)}\n" + footer


def _quantities() -> str:
    from ..schema import (
        DEFINITIONS,
        INTEGRATED_QUANTITIES,
        SCALAR_QUANTITIES,
        VALUE_UNITS,
        PerformanceQuantity,
    )

    rows = []
    for q in PerformanceQuantity:
        q = q.value
        units = ", ".join(f"`{u.to_string() or 'dimensionless'}`" for u in VALUE_UNITS[q])
        defs = ", ".join(f"`{d}`" for d in sorted(DEFINITIONS.get(q, []))) or "–"
        kind = "single value" if q in SCALAR_QUANTITIES else "curve vs energy"
        integ = "yes" if q in INTEGRATED_QUANTITIES else "–"
        rows.append(f"| `{q}` | {kind} | {defs} | {integ} | {units} |")
    return (
        "### Quantities\n\nAllowed values of `RecordMeta.quantity`, with the definitions "
        "each one accepts, whether it needs `energy_integration`, and the units its "
        "`value` column can have.\n\n"
        "| Quantity | Shape | `definition` | `energy_integration` | Units of `value` |\n"
        "|---|---|---|---|---|\n" + "\n".join(rows) + "\n"
    )


def api_reference() -> str:
    """Markdown of the API reference page."""
    out = [
        "# API reference\n",
        "Generated from the code of `iact_perf`. For worked examples, see the "
        "[user guide](index.md).\n",
    ]
    for title, intro, objects in SECTIONS:
        out.append(f"## {title}\n\n{intro}\n")
        out += [_object(o) for o in objects]
        if title == "Record header":
            out.append(_quantities())
    return "\n".join(out)
