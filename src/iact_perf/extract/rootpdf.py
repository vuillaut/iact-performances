"""Read data points from vector PDF figures made with ROOT (TGraph plots).

ROOT writes a PostScript-like page that Ghostscript turns into a PDF. A
``TGraph`` drawn with markers and a line (``"APL"``) is stored as one dashed
or solid polyline per graph plus one small closed path per marker. This module
recovers the markers, which are the points of the graph, and converts them to
data values:

1. The page content stream is read with :func:`iact_perf.extract.vector.parse_content`.
   ROOT draws paths in units of 0.1 pt (a ``0.1 0 0 0.1 cm`` at the top of the
   page); text comes out in points.
2. :class:`RootFigure` finds the frame from the two axis lines, the major
   tick marks of each axis, and pairs them with their labels. The x axis is
   ``log10(E / TeV)`` in the figures this module was written for (checked
   against the axis title); the y axis is linear or logarithmic (``10`` with
   an exponent).
3. :meth:`RootFigure.curves` returns the points by marker colour. A marker
   outside the frame is not drawn by ROOT, so it is not in the file: the
   reader of the paper cannot see it either. The polyline of each curve is
   clipped by ROOT at the frame: its end vertices on the frame are not data
   points and are left out.

Differences from :mod:`iact_perf.extract.vector` (matplotlib):

- Tick positions are rounded to 0.5 unit (0.05 pt) and some are off by 2.5
  units, so the calibration is a least-squares line that must reproduce every
  labelled tick within :data:`TICK_TOLERANCE`, not an exact fit. The values
  are then good to about 1 unit in 4000, i.e. 3 significant digits: round with
  ``round_sig(values, 3)``.
- A figure may have no legend (the legend of the left panel of a pair serves
  both); :meth:`RootFigure.legend` raises if there is none. A marker is
  identified by ``(colour, number of vertices)``, see :attr:`Curve.signature`.

Anything unexpected raises an error. The calibration still needs an independent
check, see ``AGENTS.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .vector import Color, PdfPath, PdfText, content_stream, font_names, parse_content

#: ROOT draws in units of 0.1 pt: 1 pt = 10 units.
UNIT = 10.0
#: Largest deviation, in path units, of a labelled tick from the fitted axis.
TICK_TOLERANCE = 5.0
#: A line longer than this (units) is an axis or a curve, not a tick or a marker.
LONG = 1000.0
#: Largest bounding box (units) of a marker.
MARKER_SIZE = 200.0
#: How far (units) a marker centre may be from a vertex of its polyline.
VERTEX_TOLERANCE = 1.5
#: A major tick is at least this fraction of the longest tick of its axis.
MAJOR_FRACTION = 0.9
#: x tick labels start more than this (pt) below the frame; the lowest y label does not.
X_LABEL_DROP = 10.0


@dataclass
class Axis:
    """Device -> data mapping of one axis: ``value = a + b * device`` (log10 if ``log``)."""

    a: float
    b: float
    log: bool
    residual: float  # largest deviation of a labelled tick, in device units
    n_ticks: int

    def __call__(self, device) -> np.ndarray:
        v = self.a + self.b * np.asarray(device, dtype=float)
        return 10**v if self.log else v


@dataclass
class RootCurve:
    color: Color
    signature: tuple  # (colour, vertices of the marker, size of the marker in units)
    x_log10: np.ndarray  # log10(E / TeV) of each marker, sorted
    y: np.ndarray
    n_edge_vertices: int  # vertices of the line that are not markers (clipped at the frame)


def _number(text: str) -> float:
    """A tick label: ROOT writes the minus sign as a soft hyphen."""
    return float(text.replace("\xad", "-").replace("−", "-"))


def _fit_axis(points: list[tuple[float, float]], log: bool) -> Axis:
    """Least-squares line through (device, value) pairs; every pair must be within tolerance."""
    if len(points) < 3:
        raise ValueError(f"need at least three labelled major ticks per axis, got {len(points)}")
    dev = np.array([p[0] for p in points])
    val = np.array([p[1] for p in points])
    b, a = np.polyfit(dev, val, 1)
    if b <= 0:
        raise ValueError("axis calibration is inverted or degenerate")
    residual = float(np.max(np.abs(val - (a + b * dev))) / b)
    if residual > TICK_TOLERANCE:
        raise ValueError(f"tick labels are not on a line: residual {residual} units, {points}")
    return Axis(float(a), float(b), log, residual, len(points))


class RootFigure:
    """A ROOT graph read from a single-page vector PDF with one frame."""

    def __init__(self, pdf: bytes):
        content = content_stream(pdf)
        if not content.startswith(b"q 0.1 0 0 0.1 0 0 cm"):
            raise ValueError("not a ROOT/Ghostscript page (no 0.1 scale at the top)")
        self.paths, self.texts = parse_content(content, font_names(pdf))
        self.frame = self._frame()
        self.x_label, self.y_label = self._titles()
        self.x = self._x_axis()
        self.y = self._y_axis()
        self._markers, self._lines = self._graphics()

    # -- structure

    def _frame(self) -> tuple[float, float, float, float]:
        """(x0, y0, x1, y1) in units, from the two long axis lines meeting at the origin."""
        two = [p for p in self.paths if len(p.pts) == 2]
        horiz = [p for p in two if abs(p.pts[0][1] - p.pts[1][1]) < 0.01 and self._length(p) > LONG]
        vert = [p for p in two if abs(p.pts[0][0] - p.pts[1][0]) < 0.01 and self._length(p) > LONG]
        # legend boxes are drawn with the same kind of lines: the axes are the ones
        # that start at the bottom-left corner of the frame
        for h in horiz:
            for v in vert:
                x0 = min(q[0] for q in h.pts)
                y0 = min(q[1] for q in v.pts)
                if abs(v.pts[0][0] - x0) < 0.01 and abs(h.pts[0][1] - y0) < 0.01:
                    return x0, y0, max(q[0] for q in h.pts), max(q[1] for q in v.pts)
        raise ValueError("no pair of axis lines meeting at the frame corner found")

    @staticmethod
    def _length(p: PdfPath) -> float:
        return abs(p.pts[0][0] - p.pts[1][0]) + abs(p.pts[0][1] - p.pts[1][1])

    def _titles(self) -> tuple[str, str]:
        x0, y0, x1, y1 = (v / UNIT for v in self.frame)
        rotated = [t for t in self.texts if t.rotated and t.x < x0]
        below = [t for t in self.texts if not t.rotated and t.y < y0 - 1 and not self._numeric(t)]
        if len(rotated) != 1 or len(below) != 1:
            raise ValueError(f"expected one y title and one x title, got {rotated} and {below}")
        # ROOT writes the subscript of "log10" after its base: strings are in drawing order
        x_title = "".join(below[0].strings)
        # either a linear axis in log10(E/TeV), or a logarithmic axis in E (TeV), whose
        # labels are 10^n written as an exponent text followed by "10" ("1" and "10" alone)
        self._log_x_axis = x_title == "Energy (TeV)"
        if not self._log_x_axis and ("Energy/TeV" not in x_title or "log" not in x_title):
            raise ValueError(f"x axis is not log10(E/TeV): {x_title!r}")
        return x_title, rotated[0].text

    @staticmethod
    def _numeric(t: PdfText) -> bool:
        try:
            for s in t.strings:
                _number(s)
        except ValueError:
            return False
        return True

    def _major_ticks(self, vertical: bool) -> list[float]:
        """Device positions of the major tick marks attached to the frame corner."""
        x0, y0, x1, y1 = self.frame
        ticks = {}
        for p in self.paths:
            if len(p.pts) != 2 or self._length(p) > 300:
                continue
            (xa, ya), (xb, yb) = p.pts
            on_x_axis = abs(xa - xb) < 0.01 and abs(min(ya, yb) - y0) < 0.01
            on_y_axis = abs(ya - yb) < 0.01 and abs(min(xa, xb) - x0) < 0.01
            if vertical and on_x_axis and x0 - 0.01 <= xa <= x1 + 0.01:
                ticks[round(xa, 1)] = self._length(p)
            if not vertical and on_y_axis and y0 - 0.01 <= ya <= y1 + 0.01:
                ticks[round(ya, 1)] = self._length(p)
        if not ticks:
            raise ValueError("no tick marks found")
        longest = max(ticks.values())
        return sorted(pos for pos, length in ticks.items() if length >= MAJOR_FRACTION * longest)

    @staticmethod
    def _decade(t: PdfText) -> float:
        """log10 of the value of a label of a logarithmic axis: "1", "10" or exponent + "10"."""
        if len(t.strings) == 2 and t.strings[1] == "10":
            return _number(t.strings[0])
        if len(t.strings) == 1 and _number(t.strings[0]) > 0:
            return float(np.log10(_number(t.strings[0])))
        raise ValueError(f"unhandled x tick label {t.strings}")

    def _x_axis(self) -> Axis:
        x0, y0, _, _ = (v / UNIT for v in self.frame)
        labels = [
            t for t in self.texts if not t.rotated and t.y < y0 - X_LABEL_DROP and self._numeric(t)
        ]
        if self._log_x_axis:
            values = [self._decade(t) for t in labels]
        else:
            values = [_number(s) for t in labels for s in t.strings]
        ticks = self._major_ticks(vertical=True)
        if len(values) != len(ticks):
            raise ValueError(f"{len(values)} x labels for {len(ticks)} major ticks")
        return _fit_axis(list(zip(ticks, values, strict=True)), log=False)

    def _y_axis(self) -> Axis:
        x0, y0, _, y1 = (v / UNIT for v in self.frame)
        labels = [
            t for t in self.texts if not t.rotated and t.x < x0 and y0 - X_LABEL_DROP < t.y < y1 + 5
        ]
        ticks = self._major_ticks(vertical=False)
        if not labels:
            raise ValueError("no y tick labels found")
        if all(len(t.strings) == 2 and t.strings[1] == "10" for t in labels):
            # one text per label: exponent (placed at the tick) and the base 10
            pairs = []
            for t in labels:
                tick = min(ticks, key=lambda p: abs(p / UNIT - t.y))
                if abs(tick / UNIT - t.y) > 5:
                    raise ValueError(f"y label 10^{t.strings[0]} is far from any major tick")
                pairs.append((tick, _number(t.strings[0])))
            if len({p[0] for p in pairs}) != len(ticks):
                raise ValueError(f"{len(pairs)} y labels for {len(ticks)} major ticks")
            return _fit_axis(sorted(pairs), log=True)
        if len(labels) == 1 and self._numeric(labels[0]):
            values = [_number(s) for s in labels[0].strings]
            if len(values) != len(ticks):
                raise ValueError(f"{len(values)} y labels for {len(ticks)} major ticks")
            return _fit_axis(list(zip(ticks, values, strict=True)), log=False)
        raise ValueError(f"unhandled y tick labels: {[t.strings for t in labels]}")

    def _graphics(self):
        x0, y0, x1, y1 = self.frame
        markers, lines = [], []
        for p in self.paths:
            if p.paint != "S" or len(p.pts) < 3:
                continue
            xs = [q[0] for q in p.pts]
            ys = [q[1] for q in p.pts]
            if max(xs) - min(xs) > MARKER_SIZE or max(ys) - min(ys) > MARKER_SIZE:
                lines.append(p)
            else:
                centre = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)
                size = (round(max(xs) - min(xs)), round(max(ys) - min(ys)))
                markers.append((p, centre, size))
        return markers, lines

    # -- content

    def legend(self) -> list[tuple[tuple, str]]:
        """Legend entries: (marker signature, text). Raises if the figure has no legend."""
        entries = self._legend_entries()
        if not entries:
            raise ValueError("no legend found in the figure")
        return [(self._signature(m), t.text) for t, m in entries]

    def _legend_entries(self):
        """(text, marker) pairs. A legend text is an unrotated text inside the frame;
        its marker is the one just left of it at the same height. Empty if there is
        no such text; raises if a text matches no marker or several."""
        x0, y0, x1, y1 = self.frame
        texts = [
            t for t in self.texts if not t.rotated and x0 < t.x * UNIT < x1 and y0 < t.y * UNIT < y1
        ]
        out = []
        for t in texts:
            near = [
                m
                for m in self._markers
                if 50 < t.x * UNIT - m[1][0] < 400 and abs(t.y * UNIT - m[1][1]) < 100
            ]
            if len(near) != 1:
                raise ValueError(f"legend text {t.text!r} has {len(near)} candidate markers")
            out.append((t, near[0]))
        return out

    @staticmethod
    def _signature(marker) -> tuple:
        path, _, size = marker
        return (path.color, len(path.pts), size)

    def curves(self) -> dict[tuple, RootCurve]:
        """Points of the graphs by marker signature, in data units, sorted by energy.

        ``x_log10`` is log10(E/TeV). The legend markers are left out. Every
        marker centre must coincide with a vertex of the polyline of its
        colour, and every polyline must be made of its markers and at most two
        vertices clipped at the frame: this checks that the markers read are
        the points of the curve. Markers outside the frame raise an error
        (ROOT does not draw them, so finding one means the file is not what
        this reader expects).
        """
        x0, y0, x1, y1 = self.frame
        legend_markers = {id(m) for _, m in self._legend_entries()}
        data = [m for m in self._markers if id(m) not in legend_markers]
        by_sig: dict[tuple, list] = {}
        for m in data:
            c = m[1]
            if not (x0 - 0.01 <= c[0] <= x1 + 0.01 and y0 - 0.01 <= c[1] <= y1 + 0.01):
                raise ValueError(f"marker centre {c} outside the frame {self.frame}")
            by_sig.setdefault(self._signature(m), []).append(m)
        if not by_sig:
            raise ValueError("no data marker found")
        out = {}
        for sig, ms in by_sig.items():
            lines = [p for p in self._lines if p.color == sig[0]]
            if len(lines) != 1:
                raise ValueError(f"{len(lines)} polylines of colour {sig[0]}, expected 1")
            vertices = lines[0].pts
            centres = [m[1] for m in ms]
            matched = [
                v
                for v in vertices
                if any(abs(v[0] - c[0]) < VERTEX_TOLERANCE and abs(v[1] - c[1]) < VERTEX_TOLERANCE
                       for c in centres)
            ]  # fmt: skip
            # the other vertices are where ROOT clips the line: on the frame
            edge = [v for v in vertices if v not in matched]
            on_frame = [
                v
                for v in edge
                if min(abs(v[0] - x0), abs(v[0] - x1), abs(v[1] - y0), abs(v[1] - y1))
                < VERTEX_TOLERANCE
            ]
            n_edge = len(edge)
            if len(matched) != len(centres) or len(on_frame) != n_edge or n_edge > 2:
                raise ValueError(
                    f"{sig}: {len(centres)} markers, {len(matched)} of {len(vertices)} "
                    f"line vertices match them, {len(on_frame)} of the others are on the frame"
                )
            centres.sort()
            xs = np.array([c[0] for c in centres])
            ys = np.array([c[1] for c in centres])
            out[sig] = RootCurve(
                sig[0], sig, np.log10(self.x(xs)) if self.x.log else self.x(xs), self.y(ys), n_edge
            )
        return out


def round_sig(values, digits: int = 3) -> np.ndarray:
    """Round to ``digits`` significant digits (3 by default: the resolution of a ROOT PDF)."""
    return np.array([float(f"{v:.{digits}g}") for v in np.atleast_1d(values)])


def eps_to_pdf(eps: bytes) -> bytes:
    """Convert an EPS file written by ROOT into the PDF page :class:`RootFigure` reads.

    Runs Ghostscript (``gs`` must be installed), the converter that also makes the
    PDF figures of ROOT users. Only the page content is used afterwards, so the
    metadata Ghostscript adds (dates) do not matter.
    """
    import shutil
    import subprocess

    gs = shutil.which("gs")
    if gs is None:
        raise RuntimeError("Ghostscript (gs) is needed to read EPS figures and is not installed")
    run = subprocess.run(
        [gs, "-q", "-dBATCH", "-dNOPAUSE", "-dSAFER", "-dEPSCrop", "-sDEVICE=pdfwrite",
         "-sOutputFile=-", "-"],
        input=eps,
        capture_output=True,
        check=True,
    )  # fmt: skip
    return run.stdout
