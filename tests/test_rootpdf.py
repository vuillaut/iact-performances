"""The ROOT figure reader, on a synthetic page written the way ROOT + Ghostscript write one.

No real figure is committed: the page is built here with known data.
"""

import zlib

import numpy as np
import pytest

from iact_perf.extract.rootpdf import RootFigure, _fit_axis, _number, round_sig

X0, Y0, X1, Y1 = 500.0, 500.0, 5500.0, 4500.0  # frame, in ROOT units (0.1 pt)
BLUE, RED = (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)
#: log10(E/TeV) of the points and their values, for a linear and a log y axis
LOGE = np.array([-0.5, 0.0, 0.5, 1.0, 1.5, 2.0])
Y_LIN = np.array([0.2, 0.35, 0.3, 0.6, 0.5, 0.9])
Y_LOG = np.array([30.0, 300.0, 3000.0, 20000.0, 50000.0, 90000.0])


def x_dev(logE):
    return 500 + 1000 * (np.asarray(logE) + 1)  # log10 E from -1 to 4


def y_lin_dev(y):
    return 500 + 4000 * np.asarray(y)  # 0 to 1


def y_log_dev(y):
    return 500 + 1000 * (np.log10(np.asarray(y)) - 1)  # 10 to 10^5


def text(x, y, strings, rotated=False):
    tm = "0 1 -1 0" if rotated else "1 0 0 1"
    body = "".join(f"({s})Tj\n/R8 12 Tf\n" for s in strings)
    return f"q\n10 0 0 10 0 0 cm BT\n/R8 18 Tf\n{tm} {x} {y} Tm\n{body}ET\nQ\n"


def line(x0, y0, x1, y1):
    return f"{x0} {y0} m\n{x1} {y1} l\nS\n"


def marker(kind, cx, cy, rgb):
    h = 32.5
    pts = {
        "triangle": [(cx, cy + h), (cx - h, cy - h), (cx + h, cy - h)],
        "square": [(cx + h, cy + h), (cx - h, cy + h), (cx - h, cy - h), (cx + h, cy - h),
                   (cx + h, cy + h)],
    }[kind]  # fmt: skip
    path = f"{pts[0][0]} {pts[0][1]} m\n" + "".join(f"{x} {y} l\n" for x, y in pts[1:])
    return f"{rgb[0]} {rgb[1]} {rgb[2]} RG\n7.5 w\n[] 0 d\n{path}S\n"


def polyline(xs, ys, rgb, edge=True):
    pts = list(zip(xs, ys, strict=True))
    if edge:  # ROOT clips the line at the frame: one extra vertex on the frame
        pts.append((X1, pts[-1][1] + 100))
    path = f"{pts[0][0]} {pts[0][1]} m\n" + "".join(f"{x} {y} l\n" for x, y in pts[1:])
    return f"{rgb[0]} {rgb[1]} {rgb[2]} RG\n7.5 w\n[40 20] 0 d\n{path}S\n"


def page(
    log_y=False, legend=True, x_title=None, shift_label=0.0, extra="", drop_marker=None, log_x=False
):
    ydev = y_log_dev if log_y else y_lin_dev
    out = ["q 0.1 0 0 0.1 0 0 cm\n"]
    out.append(line(X0, Y0, X1, Y0) + line(X0, Y0, X0, Y1))
    # x ticks: majors every 1 (labels 0..3), minors every 0.5
    for v in np.arange(-1, 4.01, 0.5):
        major = float(v).is_integer() and v >= 0
        if float(v).is_integer() and v < 0:
            continue
        out.append(line(x_dev(v), Y0 + (120 if major else 60), x_dev(v), Y0))
    if log_x:  # one label per decade, "1", "10", then exponent and "10" (ROOT's way)
        labels = [["1"], ["10"], ["2", "10"], ["3", "10"], ["4", "10"]]
        for v, strings in zip(range(5), labels, strict=True):
            out.append(text(x_dev(v) / 10 - 5, 30, strings))
        x_title = text(400, 16, list("Energy ") + ["\\(", "T", "e", "V", "\\)"])
    else:
        out.append(text(60, 30, ["0", "1", "2", "3", "4"]))
    out.append(text(400, 16, list("(Energy/TeV)") + ["10", "log"]) if x_title is None else x_title)
    # y ticks and labels
    if log_y:
        for e in range(1, 6):
            out.append(line(X0 + 135, ydev(10.0**e), X0, ydev(10.0**e)))
            out.append(text(44.8, ydev(10.0**e) / 10 + 1, [str(e), "10"]))
            if e < 5:  # a minor tick
                out.append(line(X0 + 67.5, ydev(3 * 10.0**e), X0, ydev(3 * 10.0**e)))
        out.append(text(17.9, 340, list("Effective Area"), rotated=True))
    else:
        labels = []
        for v in (0, 0.25, 0.5, 0.75, 1):
            out.append(line(X0 + 135, ydev(v), X0, ydev(v)))
            labels.append(f"{v:g}" if v != 0.75 else "0.75")
        out.append(line(X0 + 67.5, ydev(0.125), X0, ydev(0.125)))
        out.append(text(44.0, 44.1, labels))
        out.append(text(16.2, 130, ["Angular Resolution"], rotated=True))
    # curves
    ys = Y_LOG if log_y else Y_LIN
    series = [
        ("triangle", BLUE, ys, "Loose"),
        ("square", RED, ys * (0.5 if log_y else 0.8), "Std"),
    ]
    for i, (kind, rgb, vals, name) in enumerate(series):
        xs, yy = x_dev(LOGE), ydev(vals)
        out.append(polyline(xs, yy, rgb))
        for j, (cx, cy) in enumerate(zip(xs, yy, strict=True)):
            if drop_marker != (i, j):
                out.append(marker(kind, cx, cy, rgb))
        if legend:
            ly = 4200 - 250 * i
            out.append(marker(kind, 3855, ly, rgb))
            out.append(text(402.3, ly / 10 - 4.7, [name]))
    out.append(extra)
    out.append("Q\n")
    return "".join(out).encode("latin1")


def pdf(content: bytes) -> bytes:
    comp = zlib.compress(content)
    head = f"%PDF-1.4\n1 0 obj\n<< /Length {len(comp)} /Filter /FlateDecode >>\nstream\n"
    return head.encode() + comp + b"\nendstream\nendobj\n"


def test_points_are_recovered_on_a_linear_axis():
    fig = RootFigure(pdf(page()))
    assert fig.y_label == "Angular Resolution"
    assert not fig.y.log
    curves = fig.curves()
    assert len(curves) == 2
    blue = next(c for c in curves.values() if c.color == BLUE)
    np.testing.assert_allclose(blue.x_log10, LOGE, atol=1e-9)
    np.testing.assert_allclose(blue.y, Y_LIN, atol=1e-9)
    assert blue.n_edge_vertices == 1
    red = next(c for c in curves.values() if c.color == RED)
    np.testing.assert_allclose(red.y, 0.8 * Y_LIN, atol=1e-9)


def test_decade_labels_on_a_logarithmic_energy_axis():
    fig = RootFigure(pdf(page(log_x=True)))
    blue = next(c for c in fig.curves().values() if c.color == BLUE)
    np.testing.assert_allclose(blue.x_log10, LOGE, atol=1e-9)


def test_points_are_recovered_on_a_log_axis():
    fig = RootFigure(pdf(page(log_y=True)))
    assert fig.y.log
    blue = next(c for c in fig.curves().values() if c.color == BLUE)
    np.testing.assert_allclose(blue.x_log10, LOGE, atol=1e-9)
    np.testing.assert_allclose(blue.y, Y_LOG, rtol=1e-9)


def test_legend_names_the_curves_and_is_not_a_curve():
    fig = RootFigure(pdf(page()))
    legend = dict((sig[0], name) for sig, name in fig.legend())
    assert legend == {BLUE: "Loose", RED: "Std"}
    # legend markers are not data: six points per curve
    assert all(len(c.y) == 6 for c in fig.curves().values())
    # same marker signatures in the legend and in the curves
    assert {sig for sig, _ in fig.legend()} == set(fig.curves())


def test_no_legend_is_an_error_for_legend_but_not_for_curves():
    fig = RootFigure(pdf(page(legend=False)))
    with pytest.raises(ValueError, match="no legend"):
        fig.legend()
    assert len(fig.curves()) == 2


def test_not_a_root_page_fails():
    with pytest.raises(ValueError, match="not a ROOT"):
        RootFigure(pdf(b"0 0 m\n10 10 l\nS\n"))


def test_x_axis_must_be_log10_energy():
    bad = text(400, 16, list("Time in s"))
    with pytest.raises(ValueError, match="log10"):
        RootFigure(pdf(page(x_title=bad)))


def test_tick_labels_off_the_line_fail():
    content = page().decode("latin1").replace("(0.5)Tj", "(0.6)Tj").encode("latin1")
    with pytest.raises(ValueError, match="not on a line"):
        RootFigure(pdf(content))


def test_marker_outside_the_frame_fails():
    extra = marker("square", 5000, 4800, RED)
    with pytest.raises(ValueError, match="outside the frame"):
        RootFigure(pdf(page(extra=extra))).curves()


def test_marker_off_the_line_fails():
    # a marker that is not on a vertex of the polyline of its colour
    extra = marker("square", 3000, 3000, RED)
    with pytest.raises(ValueError, match="line vertices match"):
        RootFigure(pdf(page(extra=extra))).curves()


def test_missing_marker_fails():
    # the polyline keeps a vertex without a marker: more than the one clipped vertex
    fig = RootFigure(pdf(page(drop_marker=(0, 2))))
    with pytest.raises(ValueError, match="line vertices match"):
        fig.curves()


def test_fit_axis_tolerance():
    ok = _fit_axis([(0, 0.0), (1000, 1.0), (2002.5, 2.0), (3000, 3.0)], log=False)
    assert ok.residual < 3
    with pytest.raises(ValueError, match="not on a line"):
        _fit_axis([(0, 0.0), (1000, 1.0), (2020, 2.0), (3000, 3.0)], log=False)
    with pytest.raises(ValueError, match="three labelled"):
        _fit_axis([(0, 0.0), (1000, 1.0)], log=False)


def test_number_and_rounding():
    assert _number("\xad0.5") == -0.5
    assert _number("0.05") == 0.05
    np.testing.assert_array_equal(round_sig([0.123456, 12345.6]), [0.123, 12300.0])
