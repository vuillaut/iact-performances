"""Read curves from vector PDF figures made with matplotlib.

The curves of a vector figure are stored as paths with exact coordinates. This
module recovers them and converts them to data values:

1. :func:`parse_content` reads the page content stream into painted paths
   (with stroke colour, width, dash and clip rectangle) and text objects.
2. :class:`Figure` finds the panels (one clip rectangle per axes, recognised
   by its rotated y-axis label), pairs each major tick mark with the tick
   label drawn in the same ``q ... Q`` block, and fits the device-to-data
   mapping of every axis. The fit must be exact: tick labels that do not lie
   on one line raise an error instead of giving a wrong calibration.
3. :meth:`Figure.curves` returns the curves of a panel by stroke colour.
   Points outside the visible axes range are dropped: the reader of the paper
   cannot see them, so they are not published values.

It handles matplotlib PDF output only. Anything unexpected raises an error.
The calibration still needs an independent check, see
:meth:`Figure.right_axis_ticks` and ``AGENTS.md``.
"""

from __future__ import annotations

import contextlib
import re
import zlib
from dataclasses import dataclass, field

import numpy as np

BLACK = (0.0, 0.0, 0.0)
#: matplotlib default grid line colour (#b0b0b0)
GRID_GRAY = 0.6901960784
#: tolerance on device coordinates, in points
EPS = 0.1

Color = tuple[float, float, float]


# --------------------------------------------------------------------------- content stream


@dataclass
class PdfPath:
    pts: list[tuple[float, float]]
    rgb: Color  # stroke colour
    gray: float  # stroke colour when set with G
    width: float
    dashed: bool
    paint: str  # S, s, f, B, ... or n (no paint)
    clip: tuple[float, float, float, float] | None  # (x0, y0, w, h)
    block: int  # id of the innermost q ... Q block

    @property
    def color(self) -> Color:
        return round_color(self.rgb)


@dataclass
class PdfText:
    x: float
    y: float
    strings: list[str] = field(default_factory=list)
    rotated: bool = False
    block: int = 0

    @property
    def text(self) -> str:
        return "".join(self.strings)


def round_color(rgb) -> Color:
    return tuple(round(c, 3) for c in rgb)


TOKEN = re.compile(
    rb"""
    (?P<num>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)
    | (?P<str>\((?:\\.|[^\\()])*\))
    | (?P<name>/[^\s/()\[\]<>{}]+)
    | (?P<open>\[) | (?P<close>\])
    | (?P<op>[A-Za-z'"*]{1,3})
    """,
    re.VERBOSE,
)


def _decode(raw: bytes, symbol_font: bool = False) -> str:
    """Decode a PDF literal string. In the Computer Modern symbol font (CMSY,
    used by matplotlib with TeX) the minus sign is the code of ' ' or NUL."""
    out = bytearray()
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == 0x5C and i + 1 < len(raw):
            n = raw[i + 1]
            if 0x30 <= n <= 0x37:  # octal escape
                out.append(int(raw[i + 1 : i + 4], 8))
                i += 4
                continue
            out.append({0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}.get(n, n))
            i += 2
            continue
        out.append(c)
        i += 1
    text = out.decode("latin1")
    if symbol_font and text == " ":
        return "-"
    # NUL is never printed text: matplotlib Type 3 and CMSY fonts put the minus glyph there
    return text.replace("\x00", "-").replace("\u2212", "-")


def font_names(pdf: bytes) -> dict[str, str]:
    """Font resource name (``F1``) -> BaseFont (``CMSY10``) of a PDF file.

    Follows an indirect ``/Font n 0 R`` resource dictionary.
    """
    objects = {
        m.group(1): m.group(2) for m in re.finditer(rb"(\d+) 0 obj\s*(.*?)endobj", pdf, re.S)
    }
    dicts = [m.group(1) for m in re.finditer(rb"/Font\s*<<(.*?)>>", pdf, re.S)]
    dicts += [objects.get(ref, b"") for ref in re.findall(rb"/Font\s+(\d+) 0 R", pdf)]
    out = {}
    for d in dicts:
        for name, ref in re.findall(rb"/([\w.+-]+)\s+(\d+) 0 R", d):
            base = re.search(rb"/BaseFont\s*/([\w+-]+)", objects.get(ref, b""))
            if base:
                out[name.decode()] = base.group(1).decode()
    return out


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


def content_stream(pdf: bytes) -> bytes:
    """The largest decompressed content stream holding path operators (the page)."""
    best = None
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            dec = zlib.decompress(m.group(1).strip(b"\r\n"))
        except zlib.error:
            continue
        if b" m\n" in dec and (best is None or len(dec) > len(best)):
            best = dec
    if best is None:
        raise ValueError("no page content stream with path operators found")
    return best


def parse_content(
    content: bytes, fonts: dict[str, str] | None = None
) -> tuple[list[PdfPath], list[PdfText]]:
    """Tokenize a content stream into painted paths and text objects.

    ``fonts`` maps font resource names to BaseFont names (see :func:`font_names`).
    """
    fonts = fonts or {}
    symbol_font = False
    paths: list[PdfPath] = []
    texts: list[PdfText] = []
    state: dict = {
        "rgb": BLACK, "gray": 0.0, "width": 1.0, "dashed": False, "clip": None,
        "ctm": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
    }  # fmt: skip
    stack: list[dict] = []
    block = 0
    pts: list[tuple[float, float]] = []
    rect: list[float] | None = None
    pending_clip = False
    text: PdfText | None = None
    tm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)  # text matrix
    operands: list[bytes] = []

    def place_text() -> None:
        """Device position and rotation of the current text from Tm and the CTM.

        Paths are only read where the CTM is the identity (matplotlib writes
        curves in device coordinates); text is often placed with ``cm``.
        """
        if text is None:
            return
        a, b, c, d, e, f = _concat(tm, state["ctm"])
        text.x, text.y = e, f
        text.rotated = abs(b) > 1e-9 or a < 0

    def flush_path(paint: str) -> None:
        nonlocal pts
        if pts:
            paths.append(
                PdfPath(list(pts), state["rgb"], state["gray"], state["width"],
                        state["dashed"], paint, state["clip"], block)
            )  # fmt: skip
        pts = []

    for m in TOKEN.finditer(content):
        kind, tok = m.lastgroup, m.group(0)
        if kind != "op":
            operands.append(tok)
            continue
        op = tok.decode("latin1")
        nums = []
        for o in operands:
            if o[:1] not in (b"(", b"/", b"[", b"]"):
                with contextlib.suppress(ValueError):
                    nums.append(float(o))
        if op == "q":
            stack.append(dict(state))
            block += 1
        elif op == "Q":
            if stack:
                state = stack.pop()
        elif op == "cm":
            state["ctm"] = _concat(tuple(nums[-6:]), state["ctm"])
        elif op == "w":
            state["width"] = nums[-1] if nums else 1.0
        elif op == "G":
            state["gray"] = nums[-1]
            state["rgb"] = (nums[-1],) * 3
        elif op == "RG":
            state["rgb"] = tuple(nums[-3:])
        elif op == "d":
            state["dashed"] = b"[" in operands and b"]" in operands and len(nums) > 1
        elif op == "re":
            rect = nums[-4:]
        elif op == "W":
            pending_clip = True
        elif op == "n":
            if pending_clip and rect is not None:
                state["clip"] = tuple(rect)
            pending_clip = False
            flush_path("n")
        elif op == "m":
            flush_path("start")
            pts.append((nums[-2], nums[-1]))
        elif op in ("l", "c"):
            pts.append((nums[-2], nums[-1]))
        elif op in ("S", "s", "f", "F", "f*", "B", "B*", "b", "b*"):
            flush_path(op)
        elif op == "BT":
            tm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            text = PdfText(x=0.0, y=0.0, block=block)
            place_text()
        elif op == "ET":
            if text is not None and text.strings:
                texts.append(text)
            text = None
        elif op == "Tf":
            names = [o for o in operands if o[:1] == b"/"]
            if names:
                symbol_font = "CMSY" in fonts.get(names[-1][1:].decode("latin1"), "")
        elif op == "Td":
            # only the first Td of a text object places it; later ones move glyphs
            if text is not None and not text.strings:
                tm = _concat((1.0, 0.0, 0.0, 1.0, nums[-2], nums[-1]), tm)
                place_text()
        elif op == "Tm":
            if text is not None and not text.strings:
                tm = tuple(nums[-6:])
                place_text()
        elif op in ("Tj", "TJ"):
            for o in operands:
                if o[:1] == b"(" and text is not None:
                    text.strings.append(_decode(o[1:-1], symbol_font))
        operands = []
    return paths, texts


# --------------------------------------------------------------------------- figure model


@dataclass
class Tick:
    value: float  # tick value, or its log10 for '10^n' labels
    log: bool  # True for '10^n' labels
    mark: PdfPath  # the tick mark (two points)
    label: str

    @property
    def vertical(self) -> bool:
        return abs(self.mark.pts[0][0] - self.mark.pts[1][0]) < 0.01

    @property
    def position(self) -> float:
        """Device coordinate along the axis."""
        return self.mark.pts[0][0] if self.vertical else self.mark.pts[0][1]


@dataclass
class Panel:
    kind: str
    rect: tuple[float, float, float, float]  # clip rectangle (x0, y0, w, h)
    grid_v: list[float] = field(default_factory=list)
    x: tuple[float, float] | None = None  # data = x[0] + x[1] * device (log10 if x_log)
    y: tuple[float, float] | None = None
    x_log: bool = True
    y_log: bool = True

    def to_data(self, xs, ys) -> tuple[np.ndarray, np.ndarray]:
        lx = self.x[0] + self.x[1] * np.asarray(xs, dtype=float)
        ly = self.y[0] + self.y[1] * np.asarray(ys, dtype=float)
        return (10**lx if self.x_log else lx), (10**ly if self.y_log else ly)

    def contains(self, xs, ys) -> np.ndarray:
        x0, y0, w, h = self.rect
        xs, ys = np.asarray(xs), np.asarray(ys)
        return (xs >= x0 - EPS) & (xs <= x0 + w + EPS) & (ys >= y0 - EPS) & (ys <= y0 + h + EPS)


@dataclass
class Curve:
    color: Color
    x: np.ndarray  # data values, only the visible points
    y: np.ndarray
    dashed: bool
    n_outside: int  # points of the path outside the visible axes, dropped


def _parse_tick_label(text: str) -> tuple[float, bool]:
    m = re.fullmatch(r"10(-?\d+)", text)
    if m:
        return float(m.group(1)), True
    # Computer Modern draws '.' with the ':' glyph code in some matplotlib versions
    m = re.fullmatch(r"-?\d+(?:[:.]\d+)?", text)
    if m:
        return float(text.replace(":", ".")), False
    raise ValueError(f"unhandled tick label {text!r}")


def _fit(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Line through (device, value) pairs. All pairs must lie on it."""
    if len(points) < 2:
        raise ValueError("need at least two labelled ticks per axis")
    pts = sorted(points)
    xs = np.array([p[0] for p in pts])
    vs = np.array([p[1] for p in pts])
    slope = (vs[-1] - vs[0]) / (xs[-1] - xs[0])
    intercept = vs[0] - slope * xs[0]
    if np.max(np.abs(vs - (intercept + slope * xs))) > 1e-6:
        raise ValueError(f"tick labels are not on a line: {points}")
    if slope <= 0:
        raise ValueError("axis calibration is inverted or degenerate")
    return float(intercept), float(slope)


class Figure:
    """A matplotlib figure read from a single-page vector PDF.

    ``panel_labels`` maps a name for each panel to words its rotated y-axis
    label must contain (lowercase, spaces removed from the label), e.g.
    ``{"angular_resolution": ("containment", "deg"), "energy_bias": ("bias",)}``.
    Every panel of the figure must match exactly one name.
    """

    def __init__(self, pdf: bytes, panel_labels: dict[str, tuple[str, ...]]):
        self.paths, self.texts = parse_content(content_stream(pdf), font_names(pdf))
        self.ticks = self._pair_ticks()
        self.panels = self._find_panels(panel_labels)
        self._calibrate()

    # -- structure

    def _blocks(self):
        paths, texts = {}, {}
        for p in self.paths:
            paths.setdefault(p.block, []).append(p)
        for t in self.texts:
            texts.setdefault(t.block, []).append(t)
        return paths, texts

    def _pair_ticks(self) -> list[Tick]:
        """Major tick marks with their labels.

        A mark is paired with the single label drawn in the same ``q ... Q``
        block (matplotlib with TeX fonts). Otherwise (recent matplotlib draws
        marks and labels in different blocks) by position: an x label starts
        just left of its mark and sits below it; a y label ends left of its
        mark at the same height.
        """
        marks = [
            p
            for p in self.paths
            if p.paint == "B"
            and len(p.pts) == 2
            and p.clip is None
            and p.gray == 0.0
            and p.width >= 0.7  # minor ticks (0.6) are never labelled
            and max(abs(p.pts[0][0] - p.pts[1][0]), abs(p.pts[0][1] - p.pts[1][1])) < 5.0
        ]
        texts = [t for t in self.texts if not t.rotated]
        for mark in marks:
            if not (
                abs(mark.pts[0][0] - mark.pts[1][0]) < 0.01
                or abs(mark.pts[0][1] - mark.pts[1][1]) < 0.01
            ):
                raise ValueError(f"tick mark {mark.pts} is neither horizontal nor vertical")
        # One strategy per figure: mixing them pairs unlabelled marks with
        # labels of another axis.
        marks_in = {}
        for m in marks:
            marks_in.setdefault(m.block, []).append(m)
        pairs = []
        for mark in marks:
            same = [t for t in texts if t.block == mark.block]
            if len(marks_in[mark.block]) == 1 and len(same) == 1:
                pairs.append((mark, same[0]))
        if len(pairs) < 2:
            pairs = [(m, t) for m in marks if (t := self._label_near(m, texts)) is not None]
        ticks = []
        for mark, label in pairs:
            value, log = _parse_tick_label(label.text)
            ticks.append(Tick(value, log, mark, label.text))
        return ticks

    @staticmethod
    def _label_near(mark: PdfPath, texts: list[PdfText]) -> PdfText | None:
        """The label of a tick mark, by position. A label is at least ~4 pt per
        character wide, which keeps the label of another axis out."""
        (xa, ya), (xb, yb) = mark.pts
        if abs(xa - xb) < 0.01:  # vertical mark: x tick, label below, centred on it
            x, bottom = xa, min(ya, yb)
            near = [
                t
                for t in texts
                if bottom - 25 < t.y < bottom and x - 8 * len(t.text) < t.x <= x
                and t.x + 4 * len(t.text) >= x
            ]  # fmt: skip
            return min(near, key=lambda t: abs(t.x + 3 * len(t.text) - x), default=None)
        y, left = ya, min(xa, xb)  # horizontal mark: y tick, label ending on its left
        near = [
            t
            for t in texts
            if abs(t.y - y) < 8 and t.x < left and t.x + 4 * len(t.text) > left - 25
        ]
        return min(near, key=lambda t: abs(t.y - y), default=None)

    def _find_panels(self, panel_labels) -> dict[str, Panel]:
        grid = [
            p
            for p in self.paths
            if p.paint == "S" and abs(p.gray - GRID_GRAY) < 1e-6 and len(p.pts) == 2
        ]
        rects = sorted({p.clip for p in grid if p.clip is not None}, key=lambda r: (r[0], -r[1]))
        if len(rects) != len(panel_labels):
            raise ValueError(f"expected {len(panel_labels)} panels, found {len(rects)}: {rects}")
        # y-axis labels are rotated texts left of their panel, in the same
        # vertical order as the panels of their column
        labels: dict[tuple, PdfText] = {}
        for x0 in sorted({r[0] for r in rects}):
            column = [r for r in rects if abs(r[0] - x0) < EPS]  # top to bottom
            left = sorted(
                (t for t in self.texts if t.rotated and x0 - 80 < t.x < x0),
                key=lambda t: -t.y,
            )
            if len(left) != len(column):
                raise ValueError(
                    f"column at x={x0}: {len(column)} panels but y labels {[t.text for t in left]}"
                )
            labels.update(zip(column, left, strict=True))
        panels = {}
        for rect in rects:
            mine = [p for p in grid if p.clip == rect]
            grid_v = sorted({p.pts[0][0] for p in mine if abs(p.pts[0][0] - p.pts[1][0]) < 0.01})
            words = labels[rect].text.lower().replace(" ", "")
            names = [k for k, ws in panel_labels.items() if all(w in words for w in ws)]
            if len(names) != 1:
                raise ValueError(f"panel {rect}: y label {words!r} matches {names}")
            if names[0] in panels:
                raise ValueError(f"two panels match {names[0]!r}")
            panels[names[0]] = Panel(kind=names[0], rect=rect, grid_v=grid_v)
        return panels

    def _calibrate(self) -> None:
        """x: ticks hanging below a panel's bottom spine (shared by panels with
        the same vertical grid); y: ticks attached to the left spine."""
        x_by_panel: dict[str, list[Tick]] = {k: [] for k in self.panels}
        for t in self.ticks:
            if not t.vertical:
                continue
            spine = max(t.mark.pts[0][1], t.mark.pts[1][1])
            match = [k for k, p in self.panels.items() if abs(p.rect[1] - spine) < EPS]
            if len(match) == 1:
                x_by_panel[match[0]].append(t)
        for name, panel in self.panels.items():
            ticks = x_by_panel[name] or [
                t
                for other, ts in x_by_panel.items()
                if self.panels[other].grid_v == panel.grid_v
                for t in ts
            ]
            if not ticks:
                raise ValueError(f"panel {name}: no labelled x ticks")
            panel.x_log = self._same_scale(ticks, name, "x")
            panel.x = _fit([(t.position, t.value) for t in ticks])

            x0, y0, _, h = panel.rect
            y_ticks = [
                t
                for t in self.ticks
                if not t.vertical
                and abs(x0 - max(t.mark.pts[0][0], t.mark.pts[1][0])) < EPS
                and y0 - EPS <= t.position <= y0 + h + EPS
            ]
            if not y_ticks:
                raise ValueError(f"panel {name}: no labelled y ticks")
            panel.y_log = self._same_scale(y_ticks, name, "y")
            panel.y = _fit([(t.position, t.value) for t in y_ticks])

    @staticmethod
    def _same_scale(ticks, name, axis) -> bool:
        if not all(t.log == ticks[0].log for t in ticks):
            raise ValueError(f"panel {name}: mixed log and linear {axis} tick labels")
        return ticks[0].log

    # -- content

    def curves(self, name: str, min_points: int = 5, min_width: float = 1.0) -> dict[Color, Curve]:
        """Stroked curves of a panel by colour, in data units, visible points only.

        Grid lines, spines and ticks are left out by ``min_points`` and
        ``min_width``. Two curves of the same colour in one panel raise an error.
        """
        panel = self.panels[name]
        out: dict[Color, Curve] = {}
        for p in self.paths:
            if not (
                p.paint == "S"
                and p.clip == panel.rect
                and len(p.pts) >= min_points
                and p.width >= min_width
            ):
                continue
            if p.color in out:
                raise ValueError(f"panel {name}: two curves of colour {p.color}")
            xs = np.array([q[0] for q in p.pts])
            ys = np.array([q[1] for q in p.pts])
            inside = panel.contains(xs, ys)
            x, y = panel.to_data(xs[inside], ys[inside])
            out[p.color] = Curve(p.color, x, y, p.dashed, int((~inside).sum()))
        return out

    def legend(self) -> list[tuple[Color, str]]:
        """Legend entries of all panels: (colour of the sample line, legend text).

        A sample line is a short horizontal stroke outside the axes; its text
        is the nearest unrotated text just right of it, at the same height.
        """
        out = []
        for p in self.paths:
            if not (p.paint == "S" and p.clip is None and len(p.pts) in (2, 3) and p.width > 1):
                continue
            xs = [q[0] for q in p.pts]
            ys = [q[1] for q in p.pts]
            if max(ys) - min(ys) > 0.01 or not 5 < max(xs) - min(xs) < 60:
                continue
            near = [
                t
                for t in self.texts
                if not t.rotated and 0 < t.x - max(xs) < 30 and abs(t.y - ys[0]) < 10
            ]
            if near:
                text = min(near, key=lambda t: t.x - max(xs)).text
                out.append((p.color, text))
        return out

    def right_axis_ticks(self, name: str) -> list[tuple[float, float]]:
        """Labelled major ticks of a twin axis on the right of a panel:
        (value of the tick label, value the left-axis calibration gives there).

        Use it as an independent check of the calibration, e.g. a right axis
        in arcmin must read 60 times the left axis in degrees.
        """
        panel = self.panels[name]
        x0, y0, w, h = panel.rect
        right = x0 + w
        # matplotlib draws a twin axis in one block, so pair marks and labels by position:
        # the label is the nearest unrotated text right of the mark, at the same height
        marks = [
            p
            for p in self.paths
            if p.paint == "B"
            and len(p.pts) == 2
            and p.clip is None
            and p.width >= 0.7
            and abs(p.pts[0][1] - p.pts[1][1]) < 0.01
            and abs(min(p.pts[0][0], p.pts[1][0]) - right) < EPS
            and y0 - EPS <= p.pts[0][1] <= y0 + h + EPS
        ]
        out = []
        for mark in marks:
            y = mark.pts[0][1]
            near = [t for t in self.texts if not t.rotated and t.x > right and abs(t.y - y) < 8]
            if not near:
                continue
            label = min(near, key=lambda t: (t.x - right) + abs(t.y - y)).text
            tick, log = _parse_tick_label(label)
            _, value = panel.to_data([x0], [y])
            out.append((10**tick if log else tick, float(value[0])))
        return sorted(out, key=lambda lv: lv[1])


def round_sig(values, digits: int = 6) -> np.ndarray:
    """Round to ``digits`` significant digits: the plotted precision of a figure
    is far below the float precision of its path coordinates."""
    return np.array([float(f"{v:.{digits}g}") for v in np.atleast_1d(values)])
