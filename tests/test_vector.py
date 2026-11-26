"""The vector figure reader, on a matplotlib figure with known data."""

import numpy as np
import pytest

from iact_perf.extract.vector import Figure, _decode, _fit, _parse_tick_label, round_sig

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("pdf")
import matplotlib.pyplot as plt  # noqa: E402

ORANGE = (0.937, 0.486, 0.0)
BLUE = (0.0, 0.694, 0.918)
X = np.geomspace(0.05, 100, 12)
Y_RES = 0.3 * X**-0.5
Y_BIAS = 0.3 * np.exp(-X) + 0.01
Y_BIAS[0] = 0.6  # above the visible axis range: must be dropped
LABELS = {"angular_resolution": ("containment", "deg"), "energy_bias": ("bias",)}


@pytest.fixture(scope="module")
def figure(tmp_path_factory):
    fig, (a1, a2) = plt.subplots(2, 1, sharex=True)
    a1.loglog(X, Y_RES, color=ORANGE, lw=1.5, marker="o", label="FreePACT")
    a1.loglog(X, 1.2 * Y_RES, color=BLUE, lw=1.5, label="ImPACT")
    a1.grid()
    a1.set_ylabel("68% containment radius in deg")
    a1.secondary_yaxis("right", functions=(lambda d: d * 60, lambda m: m / 60))
    a1.legend()
    a2.semilogx(X, Y_BIAS, color=ORANGE, lw=1.5)
    a2.grid()
    a2.set_ylabel("Energy Bias")
    a2.set_ylim(-0.1, 0.4)
    a2.set_xlabel("True energy in TeV")
    path = tmp_path_factory.mktemp("fig") / "fig.pdf"
    fig.savefig(path)
    plt.close(fig)
    return Figure(path.read_bytes(), LABELS)


def test_panels_and_calibration(figure):
    assert set(figure.panels) == set(LABELS)
    res = figure.panels["angular_resolution"]
    assert res.x_log and res.y_log
    assert not figure.panels["energy_bias"].y_log


def test_curves_are_exact(figure):
    curves = figure.curves("angular_resolution")
    assert set(curves) == {ORANGE, BLUE}
    np.testing.assert_allclose(curves[ORANGE].x, X, rtol=1e-6)
    np.testing.assert_allclose(curves[ORANGE].y, Y_RES, rtol=1e-6)
    np.testing.assert_allclose(curves[BLUE].y, 1.2 * Y_RES, rtol=1e-6)


def test_points_outside_axes_are_dropped(figure):
    bias = figure.curves("energy_bias")[ORANGE]
    assert bias.n_outside == 1
    np.testing.assert_allclose(bias.x, X[1:], rtol=1e-6)
    np.testing.assert_allclose(bias.y, Y_BIAS[1:], atol=1e-7)


def test_legend(figure):
    assert set(figure.legend()) == {(ORANGE, "FreePACT"), (BLUE, "ImPACT")}


def test_right_axis_is_an_independent_check(figure):
    ticks = figure.right_axis_ticks("angular_resolution")
    assert ticks
    for arcmin, deg in ticks:
        assert deg * 60 == pytest.approx(arcmin, rel=1e-6)


def test_unexpected_panel_label_fails():
    import io

    fig, ax = plt.subplots()
    ax.loglog(X, Y_RES, lw=1.5)
    ax.grid()
    ax.set_ylabel("68% containment radius in deg")
    buf = io.BytesIO()
    fig.savefig(buf, format="pdf")
    plt.close(fig)
    with pytest.raises(ValueError, match="matches"):
        Figure(buf.getvalue(), {"effective_area": ("area",)})
    with pytest.raises(ValueError, match="expected 2 panels"):
        Figure(buf.getvalue(), LABELS)


def test_tick_labels():
    assert _parse_tick_label("10-2") == (-2.0, True)
    assert _parse_tick_label("0:3") == (0.3, False)
    assert _parse_tick_label("-0.1") == (-0.1, False)
    with pytest.raises(ValueError):
        _parse_tick_label("2×10-1")


def test_decode_minus():
    assert _decode(b" ", symbol_font=True) == "-"
    assert _decode(b" ") == " "
    assert _decode(b"\\000") == "-"


def test_fit_rejects_inconsistent_ticks():
    assert _fit([(0, 0), (10, 1), (20, 2)]) == (0.0, 0.1)
    with pytest.raises(ValueError, match="not on a line"):
        _fit([(0, 0), (10, 1), (20, 3)])
    with pytest.raises(ValueError, match="two labelled ticks"):
        _fit([(0, 0)])


def test_round_sig():
    np.testing.assert_array_equal(round_sig([0.123456789, 12345.6789]), [0.123457, 12345.7])
