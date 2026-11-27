"""Read TGraphErrors points from figures written by ROOT's own PDF driver (TPDF).

ROOT's TPDF writes a figure in points, with a landscape placement
(``1 0 0 1 X Y cm 0 1 -1 0 0 0 cm``) at the top of the content stream. When
pdfTeX includes such a figure, the figure becomes a form XObject of the page
that keeps its file name (``/PTEX.FileName``): :func:`embedded_forms` returns
the content of every included figure, read from the paper PDF in memory.

A ``TGraphErrors`` (or ``TGraphAsymmErrors``) point is drawn as:

- the x error bar: two horizontal segments at the height of the point, from
  the bin edges to a gap around the marker, and optionally a vertical cap at
  each edge;
- the y error bar: two vertical segments from the gap to the error ends, with
  a horizontal cap at each end. ROOT leaves out the side of an error smaller
  than the gap: that side is not drawn, so it is not published (``nan``);
- the marker, a small filled path, drawn after its error bars.

:class:`TPdfFigure` finds the pads (frames drawn as four black lines),
calibrates each axis on its labelled major ticks, and rebuilds the points.
The point is the centre of the x error bar (the gap is symmetric around the
marker); the marker only tells which graph the point belongs to.

Anything unexpected raises an error. The calibration still needs an
independent check, see ``AGENTS.md``.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field

import numpy as np

from .rootpdf import Axis
from .vector import Color, PdfPath, PdfText, parse_content

BLACK: Color = (0.0, 0.0, 0.0)
WHITE: Color = (1.0, 1.0, 1.0)
#: Tolerance on device coordinates (pt): TPDF writes them with 3 decimals.
EPS = 0.01
#: Largest deviation (pt) of a labelled tick from the fitted axis.
TICK_TOLERANCE = 0.05
#: Largest bounding box (pt) of a marker.
MARKER_SIZE = 12.0
#: A line longer than this fraction of the frame side is an axis or a frame side.
LONG_FRACTION = 0.5
#: A major tick is at least this fraction of the longest tick of its axis.
MAJOR_FRACTION = 0.9

_NUM = rb"[-+]?(?:\d+\.?\d*|\.\d+)"
_CM = re.compile(rb"^\s*(?:(?:" + _NUM + rb"\s+){6}cm\s*)+")
_RE = re.compile(
    rb"(" + _NUM + rb")\s+(" + _NUM + rb")\s+(" + _NUM + rb")\s+(" + _NUM + rb")\s+re\b"
)
_FORM = re.compile(
    rb"/PTEX\.FileName\s*\(([^)]*)\)(?:(?!endobj).)*?stream\r?\n(.*?)endstream", re.S
)


# --------------------------------------------------------------------------- page


def embedded_forms(pdf: bytes) -> dict[str, bytes]:
    """Content streams of the figures included by pdfTeX, by file name (basename).

    The leading ``cm`` operators (ROOT's placement of the figure on its own
    page) are removed, so that paths and texts share the figure's coordinates.
    """
    out: dict[str, bytes] = {}
    for m in _FORM.finditer(pdf):
        name = m.group(1).decode("latin1").rsplit("/", 1)[-1]
        if name in out:
            raise ValueError(f"figure {name!r} included twice")
        content = zlib.decompress(m.group(2).strip(b"\r\n"))
        out[name] = _CM.sub(b"", content, count=1)
    if not out:
        raise ValueError("no figure included by pdfTeX (/PTEX.FileName) found")
    return out


def _rects_as_paths(content: bytes) -> bytes:
    """Write ``x y w h re`` as an explicit path, so that filled squares are read."""

    def sub(m: re.Match) -> bytes:
        x, y, w, h = (float(g) for g in m.groups())
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        ops = [f"{pts[0][0]:.4f} {pts[0][1]:.4f} m"]
        ops += [f"{px:.4f} {py:.4f} l" for px, py in pts[1:]]
        return (" ".join(ops) + " h").encode()

    return _RE.sub(sub, content)


# --------------------------------------------------------------------------- model


@dataclass
class Pad:
    """One frame with its calibrated axes. ``frame`` is (x0, y0, x1, y1) in pt."""

    frame: tuple[float, float, float, float]
    x: Axis
    y: Axis
    x_title: str
    y_title: str

    def contains(self, px: float, py: float) -> bool:
        x0, y0, x1, y1 = self.frame
        return x0 - EPS <= px <= x1 + EPS and y0 - EPS <= py <= y1 + EPS


@dataclass
class Graph:
    """The points of one graph, sorted by x, in data units.

    ``x`` is the axis value (log10(E/TeV) on a linear log10 axis); ``x_low`` and
    ``x_high`` are the ends of the x error bar. ``y_err_low`` and ``y_err_high``
    are positive sizes, ``nan`` where that side of the error bar is not drawn.
    """

    signature: tuple
    x: np.ndarray
    x_low: np.ndarray
    x_high: np.ndarray
    y: np.ndarray
    y_err_low: np.ndarray
    y_err_high: np.ndarray
    n_duplicates: int = 0  # points drawn twice with identical coordinates

    @property
    def color(self) -> Color:
        return self.signature[0]


@dataclass
class _Point:
    signature: tuple
    xc: float
    yc: float
    xl: float
    xh: float
    yl: float  # device position of the end of the error bar, nan if not drawn
    yh: float
    marker_centre: tuple[float, float] = field(default=(0.0, 0.0))


def _length(p: PdfPath) -> float:
    (xa, ya), (xb, yb) = p.pts[0], p.pts[-1]
    return abs(xa - xb) + abs(ya - yb)


def _horizontal(p: PdfPath) -> bool:
    return len(p.pts) == 2 and abs(p.pts[0][1] - p.pts[1][1]) < EPS


def _vertical(p: PdfPath) -> bool:
    return len(p.pts) == 2 and abs(p.pts[0][0] - p.pts[1][0]) < EPS


def _number(text: str) -> float:
    return float(text.replace("\xad", "-").replace("−", "-"))


def _is_number(text: str) -> bool:
    try:
        _number(text)
    except ValueError:
        return False
    return True


def _fit(points: list[tuple[float, float]], log: bool, minor: list[float] = ()) -> Axis:
    """Least-squares line through (device, value); every tick within TICK_TOLERANCE.

    Two labelled ticks fit any line exactly, so they are accepted only on a
    logarithmic axis whose minor ticks then fall on k x 10^n (k = 2..9), which
    checks the scale with marks the fit did not use.
    """
    if len(points) < 2 or (len(points) == 2 and not log):
        raise ValueError(f"need at least three labelled major ticks per axis, got {points}")
    dev = np.array([p[0] for p in points])
    val = np.array([p[1] for p in points])
    b, a = np.polyfit(dev, val, 1)
    if b <= 0:
        raise ValueError("axis calibration is inverted or degenerate")
    residual = float(np.max(np.abs(val - (a + b * dev))) / b)
    if residual > TICK_TOLERANCE:
        raise ValueError(f"tick labels are not on a line: residual {residual} pt, {points}")
    if log:
        _check_log_minor_ticks(float(a), float(b), minor, need=4 if len(points) == 2 else 0)
    return Axis(float(a), float(b), log, residual, len(points))


def _check_log_minor_ticks(a: float, b: float, minor: list[float], need: int) -> None:
    """Every minor tick of a log axis must map to k x 10^n, k integer in 2..9."""
    if len(minor) < need:
        raise ValueError(f"{len(minor)} minor ticks to check a two-label log axis, need {need}")
    for pos in minor:
        exponent = a + b * pos
        mantissa = 10 ** (exponent - np.floor(exponent + 1e-9))
        if abs(mantissa - round(mantissa)) > 0.01 or not 2 <= round(mantissa) <= 9:
            raise ValueError(f"minor tick at {pos} maps to {10**exponent:.4g}, not k x 10^n")


def _merge_minus(texts: list[PdfText], along_x: bool = True) -> list[tuple[float, str]]:
    """Join a lone ``-`` with the number just right of it: [(position, label)].

    The position is the x (or y) of the first piece. Texts must be on one line.
    """
    items = sorted(texts, key=lambda t: t.x)
    out: list[tuple[float, str]] = []
    skip = False
    for i, t in enumerate(items):
        if skip:
            skip = False
            continue
        s = t.text.strip()
        if s in ("-", "\xad", "−") and i + 1 < len(items) and items[i + 1].x - t.x < 12:
            out.append((t.x if along_x else t.y, "-" + items[i + 1].text.strip()))
            skip = True
        else:
            out.append((t.x if along_x else t.y, s))
    return out


class TPdfFigure:
    """A figure written by ROOT's TPDF: its pads, graphs, lines and legend."""

    def __init__(self, content: bytes):
        content = _CM.sub(b"", content, count=1)  # ROOT's placement of the figure
        self.paths, self.texts = parse_content(_rects_as_paths(content))
        if not self.paths:
            raise ValueError("no path in the figure")
        self.pads = [self._pad(f) for f in self._frames()]
        self._points, self._legend_markers = self._read_points()

    # -- structure

    def _frames(self) -> list[tuple[float, float, float, float]]:
        """Rectangles drawn as four black lines, sorted left to right, top to bottom."""
        black = [p for p in self.paths if p.color == BLACK and p.paint == "S" and len(p.pts) == 2]
        horiz = [p for p in black if _horizontal(p) and _length(p) > 50]
        vert = [p for p in black if _vertical(p) and _length(p) > 50]

        def has_h(y, xa, xb):
            return any(
                abs(h.pts[0][1] - y) < EPS
                and abs(min(q[0] for q in h.pts) - xa) < EPS
                and abs(max(q[0] for q in h.pts) - xb) < EPS
                for h in horiz
            )

        def has_v(x, ya, yb):
            return any(
                abs(v.pts[0][0] - x) < EPS
                and abs(min(q[1] for q in v.pts) - ya) < EPS
                and abs(max(q[1] for q in v.pts) - yb) < EPS
                for v in vert
            )

        frames = set()
        for h in horiz:
            x0, x1 = sorted(q[0] for q in h.pts)
            y0 = h.pts[0][1]
            for v in vert:
                if abs(v.pts[0][0] - x0) > EPS:
                    continue
                ya, y1 = sorted(q[1] for q in v.pts)
                if abs(ya - y0) > EPS:
                    continue
                if has_h(y1, x0, x1) and has_v(x1, y0, y1):
                    frames.add((round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)))
        # a legend box is drawn the same way, but has no tick marks
        frames = {f for f in frames if self._has_ticks(f)}
        if not frames:
            raise ValueError("no frame (four black lines with tick marks) found")
        return sorted(frames, key=lambda f: (-f[3], f[0]))

    def _has_ticks(self, frame) -> bool:
        try:
            return len(self._ticks(frame, True)[0]) >= 2 and len(self._ticks(frame, False)[0]) >= 2
        except ValueError:
            return False

    def _ticks(self, frame, vertical: bool) -> tuple[list[float], list[float]]:
        """Positions of the (major, minor) ticks on the bottom (x) or left (y) side of a frame."""
        x0, y0, x1, y1 = frame
        ticks: dict[float, float] = {}
        for p in self.paths:
            if p.color != BLACK or p.paint != "S" or len(p.pts) != 2:
                continue
            # a tick starts on the frame side and is short
            on_x_axis = (
                vertical
                and _vertical(p)
                and x0 - EPS <= p.pts[0][0] <= x1 + EPS
                and abs(min(q[1] for q in p.pts) - y0) < EPS
                and _length(p) < (y1 - y0) / 10
            )
            on_y_axis = (
                not vertical
                and _horizontal(p)
                and y0 - EPS <= p.pts[0][1] <= y1 + EPS
                and abs(min(q[0] for q in p.pts) - x0) < EPS
                and _length(p) < (x1 - x0) / 10
            )
            if on_x_axis:
                ticks[round(p.pts[0][0], 3)] = _length(p)
            if on_y_axis:
                ticks[round(p.pts[0][1], 3)] = _length(p)
        if not ticks:
            raise ValueError(f"no tick marks found on frame {frame}")
        longest = max(ticks.values())
        major = sorted(pos for pos, length in ticks.items() if length >= MAJOR_FRACTION * longest)
        minor = sorted(pos for pos in ticks if pos not in major)
        return major, minor

    def _pad(self, frame) -> Pad:
        x0, y0, x1, y1 = frame
        # -- x axis: the numeric texts on the baseline closest below the frame
        below = [t for t in self.texts if not t.rotated and t.y < y0 and x0 - 15 < t.x < x1 + 15]
        below = [t for t in below if t.y > y0 - 50]
        numeric = [t for t in below if _is_number(t.text) or t.text.strip() in ("-", "\xad")]
        if not numeric:
            raise ValueError(f"no x tick labels below frame {frame}")
        # the labels share one baseline; the y label "0" or the "10" of log10 are alone
        rows: dict[float, int] = {}
        for t in numeric:
            rows[round(t.y)] = rows.get(round(t.y), 0) + 1
        base = max(rows, key=lambda y: rows[y])
        x_labels = [t for t in numeric if abs(t.y - base) < 1]
        # the title: texts below the frame that are neither x labels nor y labels (left)
        title = [t for t in below if t not in x_labels and t.x > x0]
        x_title = "".join(t.text for t in sorted(title, key=lambda t: t.x))
        labels = [(pos, _number(s)) for pos, s in _merge_minus(x_labels)]
        ticks, _ = self._ticks(frame, vertical=True)
        if len(labels) != len(ticks):
            raise ValueError(f"{len(labels)} x labels for {len(ticks)} major ticks: {labels}")
        x_axis = _fit(list(zip(ticks, [v for _, v in labels], strict=True)), log=False)
        # -- y axis: texts left of the frame
        left = [
            t for t in self.texts
            if not t.rotated and x0 - 50 < t.x < x0 and y0 - 10 < t.y < y1 + 10
        ]  # fmt: skip

        def is_superscript(t: PdfText) -> bool:
            return any(2 < t.y - b.y < 10 and 0 < t.x - b.x < 25 for b in left if b is not t)

        # a "10" that is not itself the exponent of another "10" (as in 10^-10)
        bases = [t for t in left if t.text.strip() == "10" and not is_superscript(t)]
        ticks, minor = self._ticks(frame, vertical=False)
        if bases and len(bases) * 2 <= len(left):
            # logarithmic: "10" with its exponent written as superscript pieces
            values = []
            for b in bases:
                sup = [t for t in left if t is not b and 2 < t.y - b.y < 10 and 0 < t.x - b.x < 25]
                merged = _merge_minus(sup)
                if len(merged) != 1:
                    raise ValueError(f"y label 10^? at {b.y}: exponent pieces {merged}")
                values.append((b.y, _number(merged[0][1])))
            log = True
        else:
            rows: dict[float, list[PdfText]] = {}
            for t in left:
                rows.setdefault(round(t.y, 1), []).append(t)
            values = []
            for y, row in rows.items():
                merged = _merge_minus(row)
                if len(merged) != 1:
                    raise ValueError(f"y label at {y}: pieces {merged}")
                values.append((y, _number(merged[0][1])))
            log = False
        values.sort()
        if len(values) != len(ticks):
            raise ValueError(f"{len(values)} y labels for {len(ticks)} major ticks: {values}")
        y_axis = _fit(list(zip(ticks, [v for _, v in values], strict=True)), log=log, minor=minor)
        rotated = [t for t in self.texts if t.rotated and x0 - 60 < t.x < x0]
        y_title = "".join(t.text for t in sorted(rotated, key=lambda t: t.y))
        return Pad(frame, x_axis, y_axis, x_title, y_title)

    # -- points

    @staticmethod
    def _signature(p: PdfPath) -> tuple:
        xs = [q[0] for q in p.pts]
        ys = [q[1] for q in p.pts]
        return (p.color, len(p.pts), round(max(xs) - min(xs), 1), round(max(ys) - min(ys), 1))

    def _is_marker(self, p: PdfPath) -> bool:
        if p.paint not in ("f", "f*", "b", "b*", "B", "B*") or p.color in (WHITE, BLACK):
            return False
        xs = [q[0] for q in p.pts]
        ys = [q[1] for q in p.pts]
        return (
            len(p.pts) >= 3 and max(xs) - min(xs) < MARKER_SIZE and max(ys) - min(ys) < MARKER_SIZE
        )

    def _read_points(self):
        pending: dict[Color, list[PdfPath]] = {}
        points: list[_Point] = []
        # markers without error bars: legend entries
        legend: list[tuple[PdfPath, tuple[float, float]]] = []
        for p in self.paths:
            if p.paint == "S" and len(p.pts) == 2 and not p.dashed and p.color != BLACK:
                pending.setdefault(p.color, []).append(p)
            elif self._is_marker(p):
                xs = [q[0] for q in p.pts]
                ys = [q[1] for q in p.pts]
                centre = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)
                segs = pending.pop(p.color, [])
                point = self._point(p, centre, segs)
                if point is None:
                    legend.append((p, centre))
                else:
                    points.append(point)
        return points, legend

    def _point(self, marker: PdfPath, centre, segs: list[PdfPath]) -> _Point | None:
        """Rebuild a point from its marker and the segments drawn just before it.

        Returns None when there is no x error bar (a legend entry: a marker on a
        line sample); the legend check makes sure no data point is left out.
        """
        mx = centre[0]

        def straddles(s: PdfPath) -> bool:
            return min(q[0] for q in s.pts) < mx < max(q[0] for q in s.pts)

        hbar = [s for s in segs if _horizontal(s) and not straddles(s)]
        ycaps = [s for s in segs if _horizontal(s) and straddles(s)]
        vbar = [s for s in segs if _vertical(s) and abs(s.pts[0][0] - mx) < 0.05]
        xcaps = [s for s in segs if _vertical(s) and s not in vbar]
        other = [s for s in segs if not (_horizontal(s) or _vertical(s))]
        left = [s for s in hbar if max(q[0] for q in s.pts) < mx]
        right = [s for s in hbar if min(q[0] for q in s.pts) > mx]
        # a legend entry: the marker alone or on a line sample running through it
        legend_entry = not (left or right or vbar or xcaps or other)
        if legend_entry and all(_length(s) > MARKER_SIZE for s in ycaps):
            return None
        if other or len(left) != 1 or len(right) != 1:
            raise ValueError(
                f"marker at {centre}: unexpected error bars "
                f"({len(left)} left, {len(right)} right, {len(other)} oblique segments)"
            )
        yc = left[0].pts[0][1]
        if abs(right[0].pts[0][1] - yc) > EPS:
            raise ValueError(f"marker at {centre}: x error bar segments at different heights")
        inner_l = max(q[0] for q in left[0].pts)
        inner_r = min(q[0] for q in right[0].pts)
        xc = (inner_l + inner_r) / 2
        if abs(xc - mx) > 0.05:
            raise ValueError(f"marker at {centre}: x error bar not centred on it ({xc})")
        xl = min(q[0] for q in left[0].pts)
        xh = max(q[0] for q in right[0].pts)
        for c in xcaps:
            if not (abs(c.pts[0][0] - xl) < EPS or abs(c.pts[0][0] - xh) < EPS):
                raise ValueError(f"marker at {centre}: cap at x={c.pts[0][0]} not at a bar end")
        lower = [s for s in vbar if max(q[1] for q in s.pts) < yc]
        upper = [s for s in vbar if min(q[1] for q in s.pts) > yc]
        if len(lower) > 1 or len(upper) > 1 or len(lower) + len(upper) != len(vbar):
            raise ValueError(f"marker at {centre}: unexpected y error bar segments")
        yl = min(q[1] for q in lower[0].pts) if lower else np.nan
        yh = max(q[1] for q in upper[0].pts) if upper else np.nan
        ends = [v for v in (yl, yh) if not np.isnan(v)]
        for c in ycaps:
            if not any(abs(c.pts[0][1] - v) < EPS for v in ends):
                raise ValueError(f"marker at {centre}: cap at y={c.pts[0][1]} not at a bar end")
        if len(ycaps) != len(ends):
            raise ValueError(f"marker at {centre}: {len(ycaps)} y caps for {len(ends)} bar ends")
        return _Point(self._signature(marker), xc, yc, xl, xh, yl, yh, centre)

    # -- content

    def pad_of(self, px: float, py: float) -> int:
        inside = [i for i, pad in enumerate(self.pads) if pad.contains(px, py)]
        if len(inside) != 1:
            raise ValueError(f"point ({px}, {py}) is in {len(inside)} frames")
        return inside[0]

    def legend(self) -> list[tuple[int, tuple, str]]:
        """Legend entries (pad index, marker signature, text). Raises if there are none.

        A legend marker is a marker drawn without error bars. A legend text is an
        unrotated text inside a frame with exactly one legend marker just left of
        it at the same height. A text inside a frame with no legend marker next to
        it is an annotation; one with several raises. A legend marker with no
        text raises.
        """
        out = []
        for t in self.texts:
            if t.rotated:
                continue
            pads = [i for i, pad in enumerate(self.pads) if pad.contains(t.x, t.y)]
            if not pads:
                continue
            near = [
                (m, c)
                for m, c in self._legend_markers
                if 3 < t.x - c[0] < 60 and abs(t.y - c[1]) < 5
            ]
            if len(near) > 1:
                raise ValueError(f"legend text {t.text!r} has {len(near)} candidate markers")
            if near:
                out.append((pads[0], self._signature(near[0][0]), t.text, near[0][1]))
        used = {c for *_, c in out}
        lonely = [c for _, c in self._legend_markers if c not in used]
        if lonely:
            raise ValueError(f"markers without error bars and without legend text at {lonely}")
        if not out:
            raise ValueError("no legend found in the figure")
        return [(pad, sig, text) for pad, sig, text, _ in out]

    def graphs(self, pad: int) -> dict[tuple, Graph]:
        """The graphs of a pad by marker signature (legend markers excluded).

        Points drawn twice with the same coordinates are kept once and counted;
        two different points at the same x in one graph raise an error.
        """
        frame_pad = self.pads[pad]
        by_sig: dict[tuple, dict[float, _Point]] = {}
        dups: dict[tuple, int] = {}
        for p in self._points:
            if self.pad_of(p.xc, p.yc) != pad:
                continue
            seen = by_sig.setdefault(p.signature, {})
            key = round(p.xc, 2)
            if key in seen:
                q = seen[key]
                same = all(
                    (np.isnan(a) and np.isnan(b)) or abs(a - b) < EPS
                    for a, b in zip(
                        (p.yc, p.xl, p.xh, p.yl, p.yh), (q.yc, q.xl, q.xh, q.yl, q.yh), strict=True
                    )
                )
                if not same:
                    raise ValueError(f"{p.signature}: two different points at x={p.xc}")
                dups[p.signature] = dups.get(p.signature, 0) + 1
                continue
            seen[key] = p
        if not by_sig:
            raise ValueError(f"no data point in pad {pad}")
        out = {}
        for sig, pts in by_sig.items():
            ps = sorted(pts.values(), key=lambda p: p.xc)
            xc = np.array([p.xc for p in ps])
            yc = np.array([p.yc for p in ps])
            yl = np.array([p.yl for p in ps])
            yh = np.array([p.yh for p in ps])
            x_ax, y_ax = frame_pad.x, frame_pad.y
            y = y_ax(yc)
            with np.errstate(invalid="ignore"):
                err_low = y - y_ax(yl)
                err_high = y_ax(yh) - y
            # an error bar that ends on the frame is clipped: its size is not shown
            x0, y0, x1, y1 = frame_pad.frame
            err_low[np.abs(yl - y0) < EPS] = np.nan
            err_high[np.abs(yh - y1) < EPS] = np.nan
            out[sig] = Graph(
                sig,
                x_ax(xc),
                x_ax(np.array([p.xl for p in ps])),
                x_ax(np.array([p.xh for p in ps])),
                y,
                err_low,
                err_high,
                dups.get(sig, 0),
            )
        return out

    def lines(
        self, pad: int, color: Color, min_vertices: int = 3
    ) -> list[tuple[np.ndarray, np.ndarray]]:
        """Polylines of one colour in a pad, in data units, in drawing order.

        ``min_vertices=2`` also returns straight lines (e.g. a reference level);
        error bar segments are 2-vertex lines too, so use it only for a colour
        that no graph uses. Raises if a vertex is outside the frame: ROOT clips
        lines at the frame, so a vertex outside means the file is not what this
        reader expects.
        """
        frame_pad = self.pads[pad]
        out = []
        for p in self.paths:
            if p.color != color or p.paint != "S" or len(p.pts) < min_vertices:
                continue
            inside = [frame_pad.contains(*q) for q in p.pts]
            if not any(inside):
                continue
            if not all(inside):
                raise ValueError(f"polyline of colour {color} crosses the frame of pad {pad}")
            xs = np.array([q[0] for q in p.pts])
            ys = np.array([q[1] for q in p.pts])
            out.append((frame_pad.x(xs), frame_pad.y(ys)))
        return out


def round_sig(values, digits: int = 4) -> np.ndarray:
    """Round to ``digits`` significant digits; ``nan`` stays ``nan``."""
    return np.array([v if np.isnan(v) else float(f"{v:.{digits}g}") for v in np.atleast_1d(values)])
