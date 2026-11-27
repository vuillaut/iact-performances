"""The TPDF figure reader, on synthetic figures written the way ROOT's TPDF writes them.

No real figure is committed: the content streams are built here with known data.
"""

import zlib

import numpy as np
import pytest

from iact_perf.extract.rootgraph import TPdfFigure, embedded_forms, round_sig

X0, Y0, X1, Y1 = 70.0, 50.0, 530.0, 380.0  # frame, pt
GAP = 2.39  # ROOT leaves this gap (pt) around the marker in the error bars
CAP = 1.2  # half length of an error bar cap
BLUE, RED, GREY = (0.35, 0.33, 0.85), (0.92, 0.28, 0.28), (0.68, 0.74, 0.78)
LOGE = np.array([-0.4, -0.2, 0.0, 0.2, 0.4])  # log10(E/TeV) of the points
Y_BLUE = np.array([3e-11, 1e-11, 4e-12, 2e-12, 3e-12])
Y_RED = np.array([2e-12, 8e-13, 5e-13, 4e-13, 6e-13])


def x_dev(loge):
    return X0 + 115.0 * (np.asarray(loge) + 1.0)  # log10 E from -1 to 3


def y_dev(value, span=(-13, -10)):
    """Log axis from 10^lo at the bottom of the frame to 10^hi at the top."""
    lo, hi = span
    return Y0 + (Y1 - Y0) * (np.log10(np.asarray(value)) - lo) / (hi - lo)


def line(xa, ya, xb, yb, rgb=(0, 0, 0)):
    r, g, b = rgb
    return f"{r} {g} {b} RG {r} {g} {b} rg {xa:.3f} {ya:.3f} m {xb:.3f} {yb:.3f} l S\n"


def text(x, y, s):
    return f"q 0 0 566.9 403.7 re W n 1 0 0 1 {x:.3f} {y:.3f} cm BT /F4 9 Tf ({s}) Tj ET Q\n"


def marker(kind, cx, cy, rgb):
    r, g, b = rgb
    head = f"{r} {g} {b} RG {r} {g} {b} rg 0.75 w "
    if kind == "square":
        return head + f"{cx - 2.87:.3f} {cy - 2.87:.3f} 5.741 5.741 re f\n"
    return head + (
        f"{cx - 2.87:.3f} {cy - 2.87:.3f} m {cx + 2.87:.3f} {cy - 2.87:.3f} l "
        f"{cx:.3f} {cy + 2.87:.3f} l h f\n"
    )


def point(loge, y, rgb, kind, err=None, span=(-13, -10)):
    """Error bars then marker, as TGraphErrors draws a point; err = (low, high) in data."""
    cx, cy = float(x_dev(loge)), float(y_dev(y, span))
    xl, xh = float(x_dev(loge - 0.1)), float(x_dev(loge + 0.1))
    out = ["2.25 w "]
    if err is not None:
        for end in (y_dev(y - err[0], span), y_dev(y + err[1], span)):
            end = float(end)
            if abs(end - cy) > GAP:  # ROOT leaves out an error smaller than the gap
                sign = 1 if end > cy else -1
                out.append(line(cx, cy + sign * GAP, cx, end, rgb))
                out.append(line(cx - CAP, end, cx + CAP, end, rgb))
    out.append(line(xl, cy, cx - GAP, cy, rgb) + line(cx + GAP, cy, xh, cy, rgb))
    out.append(line(xl, cy - CAP, xl, cy + CAP, rgb) + line(xh, cy - CAP, xh, cy + CAP, rgb))
    out.append(marker(kind, cx, cy, rgb))
    return "".join(out)


def figure(
    span=(-13, -10),
    legend=True,
    extra="",
    blue_err=None,
    minor_shift=0.0,
    label_shift=0.0,
    twice=False,
    legend_text=True,
):
    out = ["1 0 0 1 424 255 cm 0 1 -1 0 0 0 cm 0.75 w 1 1 1 RG 1 1 1 rg\n"]
    for xa, ya, xb, yb in ((X0, Y0, X1, Y0), (X0, Y1, X1, Y1), (X0, Y0, X0, Y1), (X1, Y0, X1, Y1)):
        out.append(line(xa, ya, xb, yb))
    # x axis: majors every 1 (labels -0.5 ... 2.5 written as "-" and "0.5"), minors at 0.5
    for v in np.arange(-0.5, 2.51, 0.5):
        major = abs(v * 2 % 2 - 1) < 1e-9  # half-integers carry a label
        out.append(line(x_dev(v), Y0 + (9.8 if major else 4.9), x_dev(v), Y0))
        if major:
            if v < 0:
                out.append(text(x_dev(v) - 12, Y0 - 14, "-"))
            out.append(
                text(x_dev(v) - 5 + (label_shift if v == 1.5 else 0), Y0 - 14, f"{abs(v):g}")
            )
    out.append(
        text(450, Y0 - 31, "log") + text(466, Y0 - 38, "10") + text(476, Y0 - 31, "\\(E [TeV]\\)")
    )
    # y axis: decades with "10" and the exponent as superscript pieces, minors at 2..9
    lo, hi = span
    for e in range(int(np.floor(lo)), int(np.ceil(hi)) + 1):
        if lo <= e <= hi:
            yl = float(y_dev(10.0**e, span))
            out.append(line(X0 + 9.8, yl, X0, yl))
            out.append(
                text(X0 - 35, yl - 6, "10") + text(X0 - 20, yl, "-") + text(X0 - 15, yl, f"{-e}")
            )
        for k in range(2, 10):
            if lo <= e + np.log10(k) <= hi:
                ym = float(y_dev(k * 10.0**e, span)) + minor_shift
                out.append(line(X0 + 4.9, ym, X0, ym))
    out.append("q 1 0 0 1 30 200 cm 0 1 -1 0 0 0 cm BT /F4 9 Tf (E2 Flux Sensitivity) Tj ET Q\n")
    draws = 2 if twice else 1
    for _ in range(draws):
        for loge, y in zip(LOGE, Y_BLUE, strict=True):
            out.append(point(loge, y, BLUE, "triangle", blue_err(y) if blue_err else None, span))
        for loge, y in zip(LOGE, Y_RED, strict=True):
            out.append(point(loge, y, RED, "square", (0.3 * y, 0.3 * y), span))
    if legend:  # marker on a line sample, text to its right
        for i, (rgb, kind, name) in enumerate(
            ((BLUE, "triangle", "Graph A"), (RED, "square", "Graph B"))
        ):
            yl = Y1 - 15 - 10 * i
            out.append(line(95, yl, 120, yl, rgb) + marker(kind, 107.5, yl, rgb))
            if legend_text:
                out.append(text(125, yl - 2.5, name))
    # a guide curve with its label, next to a data marker (an annotation, not a legend)
    xs = np.linspace(-1, 3, 9)
    ys = y_dev(1e-12 * 10 ** (0.3 * xs), span)
    pts = " ".join(
        f"{x_dev(x):.3f} {y:.3f} {'m' if i == 0 else 'l'}"
        for i, (x, y) in enumerate(zip(xs, ys, strict=True))
    )
    out.append(f"[3 3] 0 d {GREY[0]} {GREY[1]} {GREY[2]} RG {pts} S [] 0 d\n")
    out.append(text(float(x_dev(-0.4)) + 8, float(y_dev(Y_BLUE[0], span)) - 2, "1 Crab"))
    out.append(extra)
    return "".join(out).encode()


def test_points_axes_and_errors():
    fig = TPdfFigure(figure(blue_err=lambda y: (0.5 * y, 0.5 * y)))
    (pad,) = fig.pads
    assert pad.x_title == "log10(E [TeV])"
    assert pad.y_title == "E2 Flux Sensitivity"
    assert pad.y.log and pad.y.n_ticks == 4
    graphs = fig.graphs(0)
    assert len(graphs) == 2
    blue = next(g for g in graphs.values() if g.color == BLUE)
    np.testing.assert_allclose(blue.x, LOGE, atol=1e-4)
    np.testing.assert_allclose(blue.x_low, LOGE - 0.1, atol=1e-4)
    np.testing.assert_allclose(blue.x_high, LOGE + 0.1, atol=1e-4)
    np.testing.assert_allclose(blue.y, Y_BLUE, rtol=1e-4)
    np.testing.assert_allclose(blue.y_err_low, 0.5 * Y_BLUE, rtol=1e-3)
    np.testing.assert_allclose(blue.y_err_high, 0.5 * Y_BLUE, rtol=1e-3)
    assert blue.n_duplicates == 0


def test_error_smaller_than_the_gap_is_not_published():
    fig = TPdfFigure(figure())
    red = next(g for g in fig.graphs(0).values() if g.color == RED)
    # 30 % up is 0.11 decade = 12 pt on this axis: drawn; 30 % down is 0.15 decade: drawn
    assert not np.isnan(red.y_err_low).any() and not np.isnan(red.y_err_high).any()
    fig = TPdfFigure(figure(blue_err=lambda y: (0.01 * y, 0.01 * y)))
    blue = next(g for g in fig.graphs(0).values() if g.color == BLUE)
    assert np.isnan(blue.y_err_low).all() and np.isnan(blue.y_err_high).all()
    np.testing.assert_allclose(blue.y, Y_BLUE, rtol=1e-4)


def test_legend_and_annotation():
    fig = TPdfFigure(figure())
    legend = {text: sig for _, sig, text in fig.legend()}
    assert set(legend) == {"Graph A", "Graph B"}  # "1 Crab" is an annotation
    graphs = fig.graphs(0)
    assert graphs[legend["Graph A"]].color == BLUE
    assert graphs[legend["Graph B"]].color == RED


def test_missing_legend_raises():
    with pytest.raises(ValueError, match="no legend"):
        TPdfFigure(figure(legend=False)).legend()
    with pytest.raises(ValueError, match="without legend text"):
        TPdfFigure(figure(legend_text=False)).legend()


def test_points_drawn_twice_are_counted():
    fig = TPdfFigure(figure(twice=True))
    for g in fig.graphs(0).values():
        assert len(g.x) == len(LOGE) and g.n_duplicates == len(LOGE)


def test_different_points_at_the_same_x_raise():
    extra = point(LOGE[1], 2 * Y_BLUE[1], BLUE, "triangle")
    with pytest.raises(ValueError, match="two different points"):
        TPdfFigure(figure(extra=extra)).graphs(0)


def test_guide_curve():
    fig = TPdfFigure(figure())
    ((x, y),) = fig.lines(0, GREY)
    np.testing.assert_allclose(y, 1e-12 * 10 ** (0.3 * x), rtol=1e-4)


def test_two_label_log_axis_is_checked_on_minor_ticks():
    span = (np.log10(2e-13), np.log10(4e-11))  # labels 1e-12 and 1e-11 only
    fig = TPdfFigure(figure(span=span))
    assert fig.pads[0].y.n_ticks == 2
    for g in fig.graphs(0).values():
        np.testing.assert_allclose(g.y, Y_BLUE if g.color == BLUE else Y_RED, rtol=1e-4)
    with pytest.raises(ValueError, match="not k x 10"):
        TPdfFigure(figure(span=span, minor_shift=3.0))


def test_misplaced_tick_label_raises():
    # the labels are paired with the ticks in order: a label at the wrong place
    # changes nothing, but a missing tick does
    extra = text(300, Y0 - 14, "7")
    with pytest.raises(ValueError, match="x labels"):
        TPdfFigure(figure(extra=extra))


def test_embedded_forms():
    def obj(n, name, content):
        stream = zlib.compress(content)
        return (
            (
                f"{n} 0 obj\n<< /Subtype /Form /PTEX.FileName ({name}) /Length {len(stream)} >>\n"
                "stream\n"
            ).encode()
            + stream
            + b"\nendstream\nendobj\n"
        )

    pdf = b"%PDF-1.5\n" + obj(1, "/compile/figures/a.pdf", figure()) + obj(2, "b.pdf", b"q Q")
    forms = embedded_forms(pdf)
    assert set(forms) == {"a.pdf", "b.pdf"}
    assert not forms["a.pdf"].lstrip().startswith(b"1 0 0 1 424")  # placement removed
    assert len(TPdfFigure(forms["a.pdf"]).graphs(0)) == 2
    with pytest.raises(ValueError, match="no figure"):
        embedded_forms(b"%PDF-1.5\n")


def test_round_sig_keeps_nan():
    out = round_sig([1.234567e-12, np.nan], 4)
    assert out[0] == 1.235e-12 and np.isnan(out[1])
