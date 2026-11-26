r"""Read numerical tables from LaTeX sources.

This is deliberately simple: it finds a ``tabular`` by the ``\label`` of its
table, splits it into rows and cells, and parses each cell into a value and
its errors. Choosing which rows and columns mean what is left to the
``extract.py`` script of each source, which knows the paper.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

UNSIGNED = r"(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
NUMBER = rf"[-+]?{UNSIGNED}"


@dataclass(frozen=True)
class Cell:
    """A parsed cell: ``value`` with ``err_low`` and ``err_high`` as positive sizes."""

    value: float
    err_low: float | None = None
    err_high: float | None = None


def strip_comments(tex: str) -> str:
    """Remove LaTeX comments (``%`` not preceded by a backslash)."""
    return re.sub(r"(?<!\\)%.*", "", tex)


def _skip_group(tex: str, pos: int) -> int:
    """Return the position after the brace group starting at ``tex[pos] == '{'``."""
    if tex[pos] != "{":
        raise ValueError(f"expected '{{' at position {pos}")
    depth = 0
    for i in range(pos, len(tex)):
        if tex[i] == "{":
            depth += 1
        elif tex[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError("unbalanced braces")


def find_table(tex: str, label: str) -> str:
    r"""Return the body of the ``tabular`` in the table labelled ``label``.

    Comments are removed first, so a commented-out table is never returned.
    """
    tex = strip_comments(tex)
    lab = tex.find(rf"\label{{{label}}}")
    if lab < 0:
        raise KeyError(f"no \\label{{{label}}} in the source")
    start = tex.rfind(r"\begin{table", 0, lab)
    end = tex.find(r"\end{table", lab)
    if start < 0 or end < 0:
        raise KeyError(f"label {label!r} is not inside a table environment")
    env = tex[start:end]

    m = re.search(r"\\begin\{(tabular\*?)\}", env)
    if m is None:
        raise KeyError(f"no tabular in table {label!r}")
    name = m.group(1)
    pos = m.end()
    # tabular has one argument (column spec), tabular* has two (width, spec)
    for _ in range(2 if name == "tabular*" else 1):
        while env[pos].isspace():
            pos += 1
        pos = _skip_group(env, pos)
    stop = env.find(rf"\end{{{name}}}", pos)
    return env[pos:stop]


def split_rows(body: str) -> list[list[str]]:
    r"""Split a tabular body into rows of raw cell strings.

    ``\hline``, ``\rule{..}{..}`` and row spacing like ``\\[0.5ex]`` are removed.
    Empty rows are dropped.
    """
    rows = []
    for raw in re.split(r"\\\\(?:\s*\[[^\]]*\])?", body):
        raw = re.sub(r"\\hline|\\cline\{[^}]*\}", "", raw)
        raw = re.sub(r"\\rule\{[^}]*\}\{[^}]*\}", "", raw)
        if not raw.strip():
            continue
        rows.append([c.strip() for c in raw.split("&")])
    return rows


def _clean(cell: str) -> str:
    cell = cell.replace("$", "")
    cell = re.sub(r"\\(?:,|;|!|\s)", "", cell)
    cell = cell.replace("~", "")
    return re.sub(r"\s+", "", cell)


def parse_cell(cell: str) -> Cell:
    r"""Parse ``"24.6 \pm 0.9"``, ``"0.157_{-0.007}^{+0.007}"`` or a plain number."""
    c = _clean(cell)

    m = re.fullmatch(rf"({NUMBER})\\pm({NUMBER})", c)
    if m:
        err = abs(float(m.group(2)))
        return Cell(float(m.group(1)), err, err)

    m = re.fullmatch(rf"({NUMBER})_\{{({NUMBER})\}}\^\{{({NUMBER})\}}", c) or re.fullmatch(
        rf"({NUMBER})\^\{{({NUMBER})\}}_\{{({NUMBER})\}}", c
    )
    if m:
        value, a, b = (float(g) for g in m.groups())
        if c.index("_") < c.index("^"):  # value_{low}^{high}
            low, high = a, b
        else:  # value^{high}_{low}
            high, low = a, b
        return Cell(value, abs(low), abs(high))

    m = re.fullmatch(NUMBER, c)
    if m:
        return Cell(float(c))
    raise ValueError(f"cannot parse table cell {cell!r}")


def parse_range(cell: str) -> tuple[float, float]:
    """Parse an energy range cell such as ``"47 - 75"``."""
    c = _clean(cell)
    m = re.fullmatch(rf"({NUMBER})(?:--|-|–)({UNSIGNED})", c)
    if not m:
        raise ValueError(f"cannot parse range {cell!r}")
    return float(m.group(1)), float(m.group(2))
