"""Digitize the markers of raster (bitmap) figures, such as ROOT plots saved as PNG.

A raster figure has no coordinates to read: only pixels. This module finds
the data points as the markers drawn in the image and converts their
positions to data values:

1. :func:`pdf_images` reads the bitmaps embedded in a PDF (in memory), with
   their page and position, so that each one can be matched to its figure.
2. :class:`RasterFigure` finds the axes frame (four long dark lines) and the
   tick marks drawn inward from it, on both sides of each axis when the plot
   mirrors them (ROOT does). Ticks are 1 pixel wide, major ticks longer than
   minor ones. The tick pattern (equal steps on a linear axis, the 2..9
   minor ticks of each decade on a logarithmic one) is found on the ticks both
   sides agree on, then fitted on all the ticks that follow it, within
   :data:`TICK_TOLERANCE` pixel.
3. The tick *labels* are pixels too, and this module does not read text: the
   extraction script gives them (:class:`Axis`), as printed, in increasing
   order. They are checked against the ticks: there must be exactly one label
   per major tick inside the frame (edges included), and they must be an
   arithmetic progression (linear) or consecutive powers of ten (log). A
   label list shifted by one step or one decade passes this check: check the
   calibration against a number quoted in the text.
4. The legend box (a dark rectangle outline inside the frame) is found, and
   the colours of its entries, from top to bottom, are matched to the legend
   texts given by the script. Each legend marker gives the shape of the
   markers of its series, and its legend line gives the row of the point in
   that shape (for a triangle it is not the middle of the shape).
5. :meth:`RasterFigure.markers` finds the markers of one series with a matched
   filter (see its docstring): the series colour scores, white scores against,
   other colours (which may cover the marker) are neutral. A marker partly
   covered by another one is placed by its visible part.

The images must not be antialiased or compressed with loss: colours are
compared exactly. A marker that is entirely covered is not found; one found
but visible below ``min_visible`` is dropped and counted. A point whose marker
centre is outside the frame is dropped and counted: the reader of the paper
cannot see it.

Precision: a marker is placed to about one pixel. :meth:`Calibration.round`
rounds values to one pixel and :attr:`Calibration.pixel_size` gives its size,
for ``provenance.digitization_uncertainty``.

Anything unexpected raises an error.
"""

from __future__ import annotations

import io
import math
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

#: maximum distance, in pixels, between a tick and the fitted tick pattern (least
#: squares on all ticks); twice that to recognise the pattern from the major ticks
TICK_TOLERANCE = 1.0
#: score of a marker candidate, as a fraction of the marker area (see ``markers``)
DETECT = 0.15
#: maximum channel value of a "dark" pixel (frame, ticks, legend box)
DARK = 40
WHITE = (255, 255, 255)
#: minimum dark fraction of each side of the frame (curves may cross it)
FRAME_COVERAGE = 0.75

Color = tuple[int, int, int]


# --------------------------------------------------------------------------- PDF images


@dataclass(frozen=True)
class PdfImage:
    """A bitmap placed on a PDF page."""

    page: int  #: page number, from 1
    name: str  #: XObject name on the page, e.g. ``/Im3``
    bbox: tuple[float, float, float, float]  #: (x0, y0, x1, y1) on the page, in points
    pixels: np.ndarray = field(repr=False)  #: (height, width, 3) uint8 RGB


def _decode_image(obj) -> np.ndarray:
    width, height = int(obj["/Width"]), int(obj["/Height"])
    if int(obj.get("/BitsPerComponent", 8)) != 8:
        raise ValueError("only 8-bit images are supported")
    filters = obj.get("/Filter")
    filters = [filters] if isinstance(filters, str) else list(filters or [])
    lossy = {"/DCTDecode", "/JPXDecode"} & {str(f) for f in filters}
    if lossy:
        raise ValueError(f"image compressed with {sorted(lossy)}: lossy, colours are not exact")
    data = obj.get_data()
    n = len(data) // (width * height)
    if n not in (1, 3) or len(data) != n * width * height:
        raise ValueError(f"unexpected image data size {len(data)} for {width}x{height}")
    arr = np.frombuffer(data, np.uint8).reshape(height, width, n)
    if n == 1:
        arr = np.repeat(arr, 3, axis=2)
    return arr.copy()


def pdf_images(pdf: bytes, min_pixels: int = 100_000) -> list[PdfImage]:
    """Bitmaps of at least ``min_pixels`` pixels drawn on the pages of ``pdf``.

    Sorted by page, then from top to bottom and left to right, so that
    panels (a) and (b) of a figure come in reading order.
    """
    import pypdf
    from pypdf.generic import ContentStream

    reader = pypdf.PdfReader(io.BytesIO(pdf))
    out: list[PdfImage] = []
    for number, page in enumerate(reader.pages, start=1):
        resources = page.get("/Resources")
        xobjects = resources.get_object().get("/XObject") if resources else None
        if not xobjects:
            continue
        xobjects = xobjects.get_object()
        ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        stack = []
        for operands, op in ContentStream(page.get_contents(), reader).operations:
            if op == b"q":
                stack.append(ctm)
            elif op == b"Q":
                ctm = stack.pop()
            elif op == b"cm":
                ctm = _concat(tuple(float(v) for v in operands), ctm)
            elif op == b"Do":
                name = str(operands[0])
                obj = xobjects[name].get_object()
                if obj.get("/Subtype") != "/Image":
                    continue
                if int(obj["/Width"]) * int(obj["/Height"]) < min_pixels:
                    continue
                a, b, c, d, e, f = ctm
                if abs(b) > 1e-6 or abs(c) > 1e-6 or a <= 0 or d <= 0:
                    raise ValueError(f"page {number} {name}: rotated or flipped image")
                out.append(PdfImage(number, name, (e, f, e + a, f + d), _decode_image(obj)))
    # panels side by side have tops a fraction of a point apart
    return sorted(out, key=lambda im: (im.page, -round(im.bbox[3] / 20), im.bbox[0]))


def _concat(m1, m2):
    """Matrix product m1 x m2 of PDF matrices (a, b, c, d, e, f)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


# --------------------------------------------------------------------------- axes


@dataclass(frozen=True)
class Axis:
    """The tick labels of one axis, as printed, in increasing order.

    ``labels`` are read from the figure by the person writing the extraction
    script: this module checks them against the tick marks it finds, see the
    module docstring.
    """

    labels: tuple[float, ...]
    log: bool = False

    def __post_init__(self):
        labels = tuple(float(v) for v in self.labels)
        object.__setattr__(self, "labels", labels)
        if len(labels) < 2:
            raise ValueError("an axis needs at least two tick labels")
        if any(b <= a for a, b in zip(labels, labels[1:], strict=False)):
            raise ValueError(f"tick labels must increase: {labels}")
        if self.log:
            exps = np.log10(labels)
            if not np.allclose(exps, np.round(exps)) or not np.allclose(np.diff(exps), 1):
                raise ValueError(f"log axis labels must be consecutive powers of ten: {labels}")
        else:
            steps = np.diff(labels)
            if not np.allclose(steps, steps[0], rtol=1e-6, atol=1e-12):
                raise ValueError(f"linear axis labels must be equally spaced: {labels}")


@dataclass(frozen=True)
class Tick:
    position: int  #: pixel column (x axis) or row (y axis)
    major: bool
    confirmed: bool  #: found, with the same length class, on both sides of the axis


@dataclass(frozen=True)
class Calibration:
    """Pixel = ``offset + scale * f(value)``, ``f`` = log10 or identity."""

    log: bool
    offset: float
    scale: float  #: pixels per unit of f(value); negative for a y axis
    n_ticks: int  #: ticks used in the fit
    max_residual: float  #: largest distance of a tick to the fit, in pixels
    n_rejected: int = 0  #: one-sided tick candidates off the tick pattern (not used)

    def to_data(self, pixels) -> np.ndarray:
        f = (np.asarray(pixels, dtype=float) - self.offset) / self.scale
        return 10**f if self.log else f

    def to_pixel(self, values) -> np.ndarray:
        values = np.asarray(values, dtype=float)
        return self.offset + self.scale * (np.log10(values) if self.log else values)

    @property
    def pixel_size(self) -> float:
        """One pixel in data units: in log10(value) for a log axis."""
        return 1.0 / abs(self.scale)

    def round(self, values) -> np.ndarray:
        """Round to the precision of one pixel: the coarsest rounding whose half
        step (the largest rounding error) is at most one pixel."""
        values = np.asarray(values, dtype=float)
        if self.log:
            relative = 10**self.pixel_size - 1  # one pixel, as a relative change
            digits = math.ceil(1 - math.log10(2 * relative))
            return np.array([float(f"{v:.{digits}g}") for v in values])
        decimals = math.ceil(-math.log10(2 * self.pixel_size))
        return np.round(values, decimals) + 0.0  # + 0.0 turns -0.0 into 0.0


def _runs(mask: np.ndarray) -> int:
    """Length of the leading run of True values."""
    return int(np.argmin(np.append(mask, False)))


def _tick_lengths(dark: np.ndarray, frame, side: str) -> dict[int, int]:
    """{position: length} of the dark runs drawn inward from one side of the frame."""
    left, right, top, bottom = frame
    out = {}
    if side in "bt":
        for x in range(left + 1, right):
            run = dark[bottom - 1 : top : -1, x] if side == "b" else dark[top + 1 : bottom, x]
            out[x] = _runs(run)
    else:
        for y in range(top + 1, bottom):
            run = dark[y, left + 1 : right] if side == "l" else dark[y, right - 1 : left : -1]
            out[y] = _runs(run)
    return out


def _side_ticks(lengths: dict[int, int], limit: int) -> dict[int, int]:
    """Isolated short runs (tick candidates): {position: length}."""
    ticks = {}
    for pos, n in lengths.items():
        if not 1 <= n <= limit:
            continue
        # a tick is one pixel wide: its neighbours are not as long
        if lengths.get(pos - 1, 0) >= n or lengths.get(pos + 1, 0) >= n:
            continue
        ticks[pos] = n
    return ticks


def _tick_classes(lengths: list[int]) -> tuple[int, int | None]:
    """(minor length, major length) from the most frequent tick lengths."""
    counts = Counter(lengths)
    common = [n for n, c in counts.most_common() if c >= 2]
    if not common:
        raise ValueError("no tick marks found")
    first = common[0]
    others = [n for n in common[1:] if abs(n - first) > 2]
    if not others:
        return first, None  # one class only: all ticks are major ticks
    second = others[0]
    return min(first, second), max(first, second)


def _axis_ticks(dark, frame, sides: str) -> list[Tick]:
    """Tick candidates of one axis, from both sides of the frame.

    A tick seen on both sides with different length classes (one side
    partly covered) is left out.
    """
    left, right, top, bottom = frame
    limit = int(0.08 * (right - left if sides == "bt" else bottom - top))
    per_side = {s: _side_ticks(_tick_lengths(dark, frame, s), limit) for s in sides}
    lengths = [n for ticks in per_side.values() for n in ticks.values()]
    minor, major = _tick_classes(lengths)

    def classify(n):
        if major is not None and abs(n - major) <= 1:
            return True
        if abs(n - minor) <= 1:
            return major is None  # one class: all major
        return None

    a, b = (
        {p: c for p, n in ticks.items() if (c := classify(n)) is not None}
        for ticks in per_side.values()
    )
    out = []
    for p in sorted(set(a) | set(b)):
        if p in a and p in b:
            if a[p] == b[p]:
                out.append(Tick(p, a[p], True))
        else:
            out.append(Tick(p, a.get(p, b.get(p)), False))
    return out


def _units(pos: np.ndarray, major: np.ndarray, log: bool, name: str) -> tuple[np.ndarray, int]:
    """Position of each tick in major steps, and the minor divisions per step (linear)."""
    if major.sum() < 2:
        raise ValueError(f"{name} axis: fewer than two major ticks found")
    pmaj = pos[major]
    step = np.diff(pmaj).min()
    k = np.round((pmaj - pmaj[0]) / step)
    if np.max(np.abs(pmaj - pmaj[0] - k * step)) > 2 * TICK_TOLERANCE:
        raise ValueError(f"{name} axis: major ticks are not equally spaced: {pmaj}")
    step = float(np.polyfit(k, pmaj, 1)[0])
    t = (pos - pmaj[0]) / step
    n_div = 1
    if log:
        units = _snap(t, log=True, n_div=1)
        # one pixel on the axis is a factor 10**(1/step) on the value
        bad = np.isnan(units) | (np.abs(units - t) * step > 2 * TICK_TOLERANCE)
        if bad.any():
            raise ValueError(f"{name} axis: ticks {pos[bad]} are not at 1..9 x 10^n")
    elif (~major).any():
        for n_div in range(2, 21):
            off = np.abs(t * n_div - np.round(t * n_div)) * step / n_div
            if np.all(off <= 2 * TICK_TOLERANCE):
                break
        else:
            raise ValueError(f"{name} axis: minor ticks do not divide the major step evenly")
        units = _snap(t, log=False, n_div=n_div)
    else:
        units = np.round(t)
    on_major = np.isclose(units, np.round(units))
    if np.any(on_major != major):
        raise ValueError(f"{name} axis: ticks {pos[on_major != major]} have the wrong length")
    return units, n_div


def _snap(t: np.ndarray, log: bool, n_div: int) -> np.ndarray:
    """Nearest tick of the pattern, in major steps (NaN if none)."""
    t = np.asarray(t, dtype=float)
    if not log:
        return np.round(t * n_div) / n_div
    decade = np.floor(t + 1e-6)
    m = np.round(10 ** (t - decade))
    with np.errstate(invalid="ignore", divide="ignore"):
        out = decade + np.log10(m)
    return np.where((m >= 1) & (m <= 10), out, np.nan)


def _calibrate(ticks: list[Tick], axis: Axis, lo: int, hi: int, name: str) -> Calibration:
    """Fit the tick pattern, match the labels to the major ticks, return a Calibration.

    Positions must increase with the value (for a y axis, pass negated rows).
    The pattern is found on the ticks confirmed by both sides of the axis when
    there are at least two major ones, else on all ticks; the other ticks are
    then added if they lie on the pattern, and counted in ``n_rejected`` if not.
    """
    confirmed = [t for t in ticks if t.confirmed]
    base = confirmed if sum(t.major for t in confirmed) >= 2 else ticks
    pos = np.array([t.position for t in base], dtype=float)
    major = np.array([t.major for t in base])
    units, n_div = _units(pos, major, axis.log, name)
    scale_units, offset_units = (float(v) for v in np.polyfit(units, pos, 1))

    n_rejected = 0
    for t in ticks:
        if t in base:
            continue
        u = _snap((t.position - offset_units) / scale_units, axis.log, n_div)
        ok = not np.isnan(u) and bool(np.isclose(u, round(float(u)))) == t.major
        if ok and abs(offset_units + scale_units * u - t.position) <= TICK_TOLERANCE:
            pos, units = np.append(pos, t.position), np.append(units, u)
        else:
            n_rejected += 1
    fit = np.polyfit(units, pos, 1)
    residual = np.abs(np.polyval(fit, units) - pos)
    if residual.max() > TICK_TOLERANCE:
        raise ValueError(f"{name} axis: tick {pos[residual.argmax()]} is off the tick pattern")
    scale_units, offset_units = (float(v) for v in fit)  # pixel = offset + scale * units

    # the major ticks inside the frame (edges included) carry the labels
    edge = 1.5
    j = np.arange(-100, 101)
    p_major = offset_units + scale_units * j
    inside = j[(p_major >= lo - edge) & (p_major <= hi + edge)]
    if len(inside) != len(axis.labels):
        raise ValueError(
            f"{name} axis: {len(inside)} major ticks in the frame, "
            f"{len(axis.labels)} labels given {axis.labels}"
        )
    f_labels = np.log10(axis.labels) if axis.log else np.asarray(axis.labels)
    per_step = f_labels[1] - f_labels[0]  # f(value) per major step
    scale = scale_units / per_step
    offset = offset_units + scale_units * inside[0] - scale * f_labels[0]
    return Calibration(
        log=axis.log,
        offset=float(offset),
        scale=float(scale),
        n_ticks=len(pos),
        max_residual=float(residual.max()),
        n_rejected=n_rejected,
    )


def _flip(cal: Calibration) -> Calibration:
    """Calibration on negated pixel positions -> calibration on the positions."""
    return Calibration(
        cal.log, -cal.offset, -cal.scale, cal.n_ticks, cal.max_residual, cal.n_rejected
    )


# --------------------------------------------------------------------------- frame and legend


def _find_frame(dark: np.ndarray) -> tuple[int, int, int, int]:
    """(left, right, top, bottom): the innermost pixel lines of the axes frame.

    The frame is the largest rectangle whose four sides are at least
    :data:`FRAME_COVERAGE` dark: curves drawn over the frame break its lines.
    """
    height, width = dark.shape
    rows = np.flatnonzero(dark.sum(axis=1) >= 0.4 * width)
    cols = np.flatnonzero(dark.sum(axis=0) >= 0.3 * height)
    best = None
    for i, top in enumerate(rows):
        for bottom in rows[i + 1 :]:
            if bottom - top < 0.2 * height:
                continue
            for j, left in enumerate(cols):
                for right in cols[j + 1 :]:
                    if right - left < 0.2 * width:
                        continue
                    area = (right - left) * (bottom - top)
                    if best is not None and area <= best[0]:
                        continue
                    sides = (
                        dark[top, left : right + 1], dark[bottom, left : right + 1],
                        dark[top : bottom + 1, left], dark[top : bottom + 1, right],
                    )  # fmt: skip
                    if all(side.mean() >= FRAME_COVERAGE for side in sides):
                        best = (area, (int(left), int(right), int(top), int(bottom)))
    if best is None:
        raise ValueError("no axes frame found (four long dark lines)")
    left, right, top, bottom = best[1]
    # thick lines: move to the innermost dark pixel line
    while dark[top + 1, left + 2 : right - 1].mean() > 0.9:
        top += 1
    while dark[bottom - 1, left + 2 : right - 1].mean() > 0.9:
        bottom -= 1
    while dark[top + 2 : bottom - 1, left + 1].mean() > 0.9:
        left += 1
    while dark[top + 2 : bottom - 1, right - 1].mean() > 0.9:
        right -= 1
    return left, right, top, bottom


def _find_legend(dark: np.ndarray, frame) -> tuple[int, int, int, int]:
    """(x0, x1, y0, y1) of the legend box, shadow included: a dark rectangle
    outline inside the frame (some of its edges may be frame lines)."""
    from scipy import ndimage

    left, right, top, bottom = frame
    inner = np.zeros_like(dark)
    inner[top + 1 : bottom, left + 1 : right] = dark[top + 1 : bottom, left + 1 : right]
    labels, n = ndimage.label(inner, structure=np.ones((3, 3)))
    found = []
    for i, sl in enumerate(ndimage.find_objects(labels), start=1):
        y0, y1, x0, x1 = sl[0].start, sl[0].stop - 1, sl[1].start, sl[1].stop - 1
        if x1 - x0 < 0.12 * (right - left) or y1 - y0 < 0.06 * (bottom - top):
            continue
        if (labels[sl] == i).mean() > 0.5:
            continue  # filled, not an outline
        # a box against the frame shares its edges with the frame lines
        y0 = top if y0 == top + 1 else y0
        x0 = left if x0 == left + 1 else x0
        y1 = bottom if y1 == bottom - 1 else y1
        x1 = right if x1 == right - 1 else x1
        # an outline: at least three of its four edges are (almost) entirely dark
        edges = (dark[y0, x0 : x1 + 1], dark[y1, x0 : x1 + 1], dark[y0 : y1 + 1, x0],
                 dark[y0 : y1 + 1, x1])  # fmt: skip
        if sum(edge.mean() > 0.8 for edge in edges) >= 3:
            found.append((x0, x1, y0, y1))
    if not found:
        raise ValueError("no legend box found in the frame")
    if len(found) > 1:
        raise ValueError(f"several legend boxes found: {found}")
    return found[0]


# --------------------------------------------------------------------------- markers


@dataclass(frozen=True)
class Template:
    """Shape of the marker of one series, cut from its legend entry."""

    mask: np.ndarray = field(repr=False)  #: True inside the marker
    #: (row, col) in ``mask`` of the point the marker shows: the row of the legend
    #: line, the middle column
    center: tuple[float, float]

    @property
    def area(self) -> int:
        return int(self.mask.sum())


@dataclass
class Markers:
    """The points of one series, sorted by x."""

    x: np.ndarray  #: data values
    y: np.ndarray
    px: np.ndarray  #: (n, 2) pixel centres (row, col)
    visible: np.ndarray  #: fraction of each marker that is visible
    n_outside: int = 0  #: markers whose centre is outside the frame (dropped)
    n_covered: int = 0  #: candidates visible below ``min_visible`` (dropped)


def _open(mask: np.ndarray, size: int) -> np.ndarray:
    from scipy import ndimage

    return ndimage.binary_opening(mask, structure=np.ones((size, size)))


def _bbox_center(mask: np.ndarray) -> tuple[float, float]:
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    return (rows[0] + rows[-1]) / 2, (cols[0] + cols[-1]) / 2


def _template(mask: np.ndarray) -> Template | None:
    """The marker of a legend entry (its colour mask), without the line through it.

    The legend line runs through the point where the marker is placed: its
    rows give the reference row of the marker (the middle of a triangle is
    not the middle of its rows). In the rows of the line, the marker is
    rebuilt from the rows just above and below it (linear interpolation of
    the row extents: exact for squares and triangles). Without a line, the
    reference is the centre of the bounding box.
    """
    from scipy import ndimage

    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if len(cols) == 0:
        return None
    c0, c1 = cols[0], cols[-1]
    line = np.flatnonzero(mask[:, c0] | mask[:, c1])  # rows of the line ends
    if len(line) == 0 or np.any(np.diff(line) != 1):
        raise ValueError(f"legend entry: unexpected line rows {line}")
    marker = mask.copy()
    if len(line) < len(rows):  # a marker sticks out of the line
        above, below = line[0] - 1, line[-1] + 1
        if not (mask[above].any() and mask[below].any()):
            raise ValueError("legend entry: the line is not inside the marker")
        ext = {r: np.flatnonzero(mask[r]) for r in (above, below)}
        for r in line:
            f = (r - above) / (below - above)
            lo = round((1 - f) * ext[above][0] + f * ext[below][0])
            hi = round((1 - f) * ext[above][-1] + f * ext[below][-1])
            marker[r] = False
            marker[r, lo : hi + 1] = True
    else:
        return None  # a line only, no marker
    labels, n = ndimage.label(marker)
    sizes = ndimage.sum(marker, labels, range(1, n + 1))
    marker = labels == (1 + int(np.argmax(sizes)))
    rows = np.flatnonzero(marker.any(axis=1))
    cols = np.flatnonzero(marker.any(axis=0))
    crop = marker[rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1]
    if min(crop.shape) < 5:
        raise ValueError(f"legend marker of {crop.shape} pixels: too small to digitize")
    if (c1 - c0) <= crop.shape[1] + 2:
        raise ValueError("legend entry: the line does not stick out of the marker")
    center = ((line[0] + line[-1]) / 2 - rows[0], (crop.shape[1] - 1) / 2)
    return Template(crop, center)


class RasterFigure:
    """A raster plot: frame, calibrated axes, legend and markers.

    ``pixels`` is an (height, width, 3) uint8 RGB array. ``legend`` gives the
    texts of the legend entries from top to bottom, as printed.
    """

    def __init__(self, pixels: np.ndarray, x: Axis, y: Axis, legend: list[str]):
        if pixels.ndim != 3 or pixels.shape[2] != 3 or pixels.dtype != np.uint8:
            raise ValueError("pixels must be an (height, width, 3) uint8 array")
        self.pixels = pixels
        self.dark = pixels.max(axis=2) <= DARK
        self.frame = _find_frame(self.dark)
        left, right, top, bottom = self.frame
        self.x_ticks = _axis_ticks(self.dark, self.frame, "bt")
        self.y_ticks = _axis_ticks(self.dark, self.frame, "lr")
        self.x = _calibrate(self.x_ticks, x, left, right, "x")
        # rows grow downward: calibrate on negated rows, so that positions grow with values
        flipped = [Tick(-t.position, t.major, t.confirmed) for t in reversed(self.y_ticks)]
        self.y = _flip(_calibrate(flipped, y, -bottom, -top, "y"))
        self.legend_box = _find_legend(self.dark, self.frame)
        self._legend = self._read_legend(list(legend))

    # ---------------------------------------------------------------- legend

    def _read_legend(self, texts: list[str]) -> dict[str, tuple[Color, Template]]:
        x0, x1, y0, y1 = self.legend_box
        region = self.pixels[y0 + 1 : y1, x0 + 1 : x1]
        counts = Counter(map(tuple, region.reshape(-1, 3).tolist()))
        entries = []
        for color, n in counts.items():
            if n < 30 or color[0] == color[1] == color[2]:  # white, black and grays
                continue
            mask = np.all(region == color, axis=2)
            template = _template(mask)
            if template is not None:
                rows = np.flatnonzero(mask.any(axis=1))
                entries.append(((rows[0] + rows[-1]) / 2, color, template))
        entries.sort(key=lambda e: e[0])
        if len(entries) != len(texts):
            raise ValueError(
                f"legend has {len(entries)} coloured markers {[e[1] for e in entries]}, "
                f"{len(texts)} texts given {texts}"
            )
        return {t: (c, tpl) for t, (_, c, tpl) in zip(texts, entries, strict=True)}

    def legend(self) -> list[tuple[str, Color]]:
        """(text, colour) of the legend entries, from top to bottom."""
        return [(t, c) for t, (c, _) in self._legend.items()]

    def template(self, text: str) -> Template:
        """The marker shape of a series, from its legend entry."""
        return self._legend[text][1]

    # ---------------------------------------------------------------- markers

    def _legend_area(self) -> tuple[slice, slice]:
        """The legend box (which includes its shadow) and a 1-pixel margin."""
        x0, x1, y0, y1 = self.legend_box
        return slice(max(y0 - 1, 0), y1 + 2), slice(max(x0 - 1, 0), x1 + 2)

    def markers(self, text: str, min_visible: float = 0.3) -> Markers:
        """Markers of the series whose legend text is ``text``, sorted by x.

        A matched filter: every pixel of the image is scored, +1 on a solid
        pixel of the series colour, -1 on white or on a thin structure of the
        series colour (a line, an error bar, a dithered band), 0 on anything
        else (another colour, which may cover the marker). The score of a
        position is the sum over the template placed there. A candidate is a
        local maximum of at least :data:`DETECT` times the template area: a
        fully visible marker scores its area, a partly covered one about its
        visible part, a line or a band less than zero. Positions of equal score
        are averaged. ``visible`` is the fraction of the template on solid
        pixels of the series colour, counting only the part of the template
        inside the frame (ROOT clips markers at the frame); candidates below ``min_visible`` are
        dropped and counted in ``n_covered``. A marker covered beyond
        :data:`DETECT` is not found at all.
        """
        from scipy import ndimage

        if text not in self._legend:
            raise KeyError(f"{text!r} not in the legend {list(self._legend)}")
        color, tpl = self._legend[text]
        own = np.all(self.pixels == color, axis=2)
        legend = self._legend_area()
        own[legend] = False
        solid = _open(own, 2)  # without 1-pixel lines and dithering

        left, right, top, bottom = self.frame
        score = np.zeros(own.shape, dtype=np.int32)
        score[np.all(self.pixels == WHITE, axis=2) | (own & ~solid)] = -1
        score[solid] = 1
        inside = np.zeros(own.shape, dtype=bool)
        inside[top + 1 : bottom, left + 1 : right] = True
        score[~inside] = 0  # outside the frame the marker is clipped: no information
        score[legend] = 0

        kernel = tpl.mask.astype(np.int32)
        total = ndimage.correlate(score, kernel, mode="constant", cval=0)
        cover = ndimage.correlate(solid.astype(np.int32), kernel, mode="constant", cval=0)
        # a marker clipped by the frame is visible only inside it
        seen = inside.copy()
        seen[legend] = False
        visible_area = ndimage.correlate(seen.astype(np.int32), kernel, mode="constant", cval=0)
        threshold = DETECT * tpl.area
        footprint = np.ones((2 * kernel.shape[0] // 3 + 1, 2 * kernel.shape[1] // 3 + 1))
        peaks = (total == ndimage.maximum_filter(total, footprint=footprint)) & (total >= threshold)
        labels, n = ndimage.label(peaks, structure=np.ones((3, 3)))
        # correlate puts the kernel origin at its centre (shape // 2)
        origin = np.array(kernel.shape) // 2
        centres, visible, n_covered = [], [], 0
        for i in range(1, n + 1):
            rows, cols = np.nonzero(labels == i)
            k = np.argmax(cover[rows, cols])
            frac = cover[rows[k], cols[k]] / max(visible_area[rows[k], cols[k]], 1)
            if frac < min_visible:
                n_covered += 1
                continue
            centres.append(
                (
                    rows.mean() - origin[0] + tpl.center[0],
                    cols.mean() - origin[1] + tpl.center[1],
                )
            )
            visible.append(frac)
        px = np.array(centres, dtype=float).reshape(-1, 2)
        vis = np.array(visible, dtype=float)
        _check_separated(px, tpl, text)
        keep = (px[:, 1] > left) & (px[:, 1] < right) & (px[:, 0] > top) & (px[:, 0] < bottom)
        order = np.argsort(px[keep, 1])
        px, vis = px[keep][order], vis[keep][order]
        return Markers(
            x=self.x.to_data(px[:, 1]),
            y=self.y.to_data(px[:, 0]),
            px=px,
            visible=vis,
            n_outside=int((~keep).sum()),
            n_covered=n_covered,
        )


def _check_separated(px: np.ndarray, tpl: Template, text: str) -> None:
    """Two markers of one series closer than half a marker: one blob found twice."""
    h, w = tpl.mask.shape
    for i in range(len(px)):
        d = np.abs(px[i + 1 :] - px[i])
        if np.any((d[:, 0] < h / 2) & (d[:, 1] < w / 2)):
            raise ValueError(f"{text}: two markers found at {px[i]}, less than half a marker apart")
