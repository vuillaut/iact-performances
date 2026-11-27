"""The raster digitizer, on synthetic plots drawn the way ROOT draws them.

No real figure is committed: the images are drawn here with known data.
"""

import io
import zlib

import numpy as np
import pytest

from iact_perf.extract.raster import Axis, RasterFigure, pdf_images

WHITE, BLACK = (255, 255, 255), (0, 0, 0)
BLUE, RED, GREEN = (0, 0, 255), (255, 0, 0), (0, 200, 0)
#: frame (left, right, top, bottom)
LEFT, RIGHT, TOP, BOTTOM = 80, 680, 50, 450
#: x: log10(E/TeV) from -1 to 2 (labels 0.1, 1, 10, 100), 200 px per decade
#: y: linear 0 to 0.5 (labels every 0.1, minor ticks every 0.02)


def x_px(e):
    return LEFT + 200 * (np.log10(e) + 1)


def y_px(v):
    return BOTTOM - 800 * np.asarray(v)


def blank(height=500, width=760):
    return np.full((height, width, 3), 255, dtype=np.uint8)


def line(img, r0, c0, r1, c1, color, width=1):
    n = int(max(abs(r1 - r0), abs(c1 - c0))) + 1
    for t in np.linspace(0, 1, 2 * n):
        r, c = round(r0 + t * (r1 - r0)), round(c0 + t * (c1 - c0))
        img[r : r + width, c : c + width] = color


def frame(img, mirrored=True):
    img[TOP, LEFT : RIGHT + 1] = BLACK
    img[BOTTOM, LEFT : RIGHT + 1] = BLACK
    img[TOP : BOTTOM + 1, LEFT] = BLACK
    img[TOP : BOTTOM + 1, RIGHT] = BLACK
    for decade in range(-1, 2):
        for m in range(1, 10):
            c = round(x_px(m * 10.0**decade))
            if not LEFT < c < RIGHT:
                continue
            n = 14 if m == 1 else 7
            img[BOTTOM - n : BOTTOM, c] = BLACK
            if mirrored:
                img[TOP + 1 : TOP + 1 + n, c] = BLACK
    for k in range(1, 25):
        r = round(y_px(0.02 * k))
        n = 18 if k % 5 == 0 else 9
        img[r, LEFT + 1 : LEFT + 1 + n] = BLACK
        if mirrored:
            img[r, RIGHT - n : RIGHT] = BLACK


def marker(img, kind, r, c, color, h=7):
    """Marker of half size ``h`` placed at (r, c), as ROOT places it."""
    r, c = round(r), round(c)
    if kind == "square":
        img[r - h : r + h + 1, c - h : c + h + 1] = color
    elif kind == "circle":
        yy, xx = np.mgrid[-h : h + 1, -h : h + 1]
        img[r - h : r + h + 1, c - h : c + h + 1][xx**2 + yy**2 <= h * h + 1] = color
    elif kind == "triangle":  # apex 2 px further from the point than the base
        for dy in range(-h - 2, h - 1):
            half = round(h * (dy + h + 2) / (2 * h + 1))
            img[r + dy, c - half : c + half + 1] = color


def legend(img, entries, x0=420, y0=60):
    """Legend box with a shadow; each entry: a line through a marker."""
    height = 30 * len(entries) + 10
    x1, y1 = x0 + 200, y0 + height
    img[y0 + 3 : y1 + 4, x0 + 3 : x1 + 4] = BLACK  # shadow
    img[y0 : y1 + 1, x0 : x1 + 1] = WHITE
    img[y0, x0 : x1 + 1] = img[y1, x0 : x1 + 1] = BLACK
    img[y0 : y1 + 1, x0] = img[y0 : y1 + 1, x1] = BLACK
    for i, (kind, color) in enumerate(entries):
        r = y0 + 20 + 30 * i
        img[r : r + 2, x0 + 10 : x0 + 60] = color  # 2-pixel line, rows r and r + 1
        marker(img, kind, r + 0.5, x0 + 35, color)


ENERGY = np.array([0.15, 0.3, 0.6, 1.2, 2.5, 5.0, 10.0])
BLUE_Y = np.array([0.30, 0.25, 0.20, 0.18, 0.16, 0.17, 0.21])
RED_Y = np.array([0.40, 0.33, 0.27, 0.22, 0.19, 0.18, 0.20])


def plot(red_y=RED_Y, with_legend=True, mirrored=True, red_kind="triangle"):
    img = blank()
    frame(img, mirrored)
    for kind, color, values in (("circle", BLUE, BLUE_Y), (red_kind, RED, red_y)):
        rows, cols = y_px(values), x_px(ENERGY)
        for i in range(len(ENERGY) - 1):
            line(img, rows[i], cols[i], rows[i + 1], cols[i + 1], color, width=2)
        for r, c in zip(rows, cols, strict=True):
            marker(img, kind, r, c, color)
    if with_legend:
        legend(img, [("circle", BLUE), (red_kind, RED)])
    return img


X_AXIS = Axis((0.1, 1, 10, 100), log=True)
Y_AXIS = Axis((0.0, 0.1, 0.2, 0.3, 0.4, 0.5))
TEXTS = ["Blue series", "Red series"]


def test_calibration_and_points():
    fig = RasterFigure(plot(), X_AXIS, Y_AXIS, TEXTS)
    assert fig.frame == (LEFT, RIGHT, TOP, BOTTOM)
    assert fig.x.max_residual <= 0.5 and fig.y.max_residual <= 0.5
    assert fig.legend() == [("Blue series", BLUE), ("Red series", RED)]
    for text, values in (("Blue series", BLUE_Y), ("Red series", RED_Y)):
        m = fig.markers(text)
        assert len(m.x) == len(ENERGY)
        # within one pixel: 1/200 decade in x, 1/800 in y
        assert np.allclose(np.log10(m.x), np.log10(ENERGY), atol=1 / 200)
        assert np.allclose(m.y, values, atol=1 / 800)


def test_triangle_reference_is_the_legend_line():
    """The triangle is drawn off-centre: its point is the row of the legend line."""
    fig = RasterFigure(plot(), X_AXIS, Y_AXIS, TEXTS)
    m = fig.markers("Red series")
    assert np.allclose(m.y, RED_Y, atol=0.6 / 800)


def test_partly_covered_marker_is_placed_by_its_visible_part():
    # the red squares cover most of the blue circles at the last three energies
    red = BLUE_Y.copy()
    red[:4] = RED_Y[:4]
    red[4:] += 6 / 800  # 6 pixels above the blue circles
    fig = RasterFigure(plot(red_y=red, red_kind="square"), X_AXIS, Y_AXIS, TEXTS)
    blue = fig.markers("Blue series")
    assert len(blue.x) == len(ENERGY)
    assert np.all(blue.visible[4:] < 0.8)
    assert np.allclose(blue.y, BLUE_Y, atol=1 / 800)
    # a strict visibility threshold drops them, and counts them
    strict = fig.markers("Blue series", min_visible=0.9)
    assert len(strict.x) == 4 and strict.n_covered == 3


def test_rounding_to_one_pixel():
    fig = RasterFigure(plot(), X_AXIS, Y_AXIS, TEXTS)
    # 1/800 per pixel: three decimals; 1/200 decade per pixel: three digits
    assert fig.y.round([0.12345])[0] == 0.123
    assert fig.x.round([1.23456])[0] == 1.23
    assert fig.y.round([-0.0001])[0] == 0.0


def test_wrong_labels_raise():
    img = plot()
    with pytest.raises(ValueError, match="major ticks in the frame"):
        RasterFigure(img, Axis((0.1, 1, 10), log=True), Y_AXIS, TEXTS)
    with pytest.raises(ValueError, match="major ticks in the frame"):
        RasterFigure(img, X_AXIS, Axis((0.0, 0.1, 0.2, 0.3, 0.4)), TEXTS)
    with pytest.raises(ValueError, match="powers of ten"):
        Axis((0.1, 1, 100), log=True)
    with pytest.raises(ValueError, match="equally spaced"):
        Axis((0.0, 0.1, 0.3))


def test_log_labels_on_a_linear_axis_raise():
    with pytest.raises(ValueError, match="1..9 x 10"):
        RasterFigure(plot(), X_AXIS, Axis((0.01, 0.1, 1), log=True), TEXTS)


def test_legend_must_exist_and_match():
    with pytest.raises(ValueError, match="no legend box"):
        RasterFigure(plot(with_legend=False), X_AXIS, Y_AXIS, TEXTS)
    with pytest.raises(ValueError, match="legend has 2 coloured markers"):
        RasterFigure(plot(), X_AXIS, Y_AXIS, ["only one"])


def test_one_sided_ticks():
    fig = RasterFigure(plot(mirrored=False), X_AXIS, Y_AXIS, TEXTS)
    m = fig.markers("Blue series")
    assert np.allclose(m.y, BLUE_Y, atol=1 / 800)


def test_no_frame_raises():
    with pytest.raises(ValueError, match="no axes frame"):
        RasterFigure(blank(), X_AXIS, Y_AXIS, TEXTS)


def test_marker_outside_the_frame_is_dropped_and_counted():
    img = plot()
    # centre 3 px right of the frame, clipped by it as ROOT does
    marker(img, "circle", y_px(0.3), RIGHT + 3, BLUE)
    img[:, RIGHT + 1 :] = WHITE
    img[TOP : BOTTOM + 1, RIGHT] = BLACK
    m = RasterFigure(img, X_AXIS, Y_AXIS, TEXTS).markers("Blue series")
    assert len(m.x) == len(ENERGY) and m.n_outside == 1


# --------------------------------------------------------------------------- PDF images


def one_image_pdf(pixels: np.ndarray, x: float, y: float, w: float, h: float) -> bytes:
    """A one-page PDF with an RGB image placed at (x, y), size (w, h) points."""
    height, width, _ = pixels.shape
    data = zlib.compress(pixels.tobytes())
    content = f"q {w} 0 0 {h} {x} {y} cm /Im1 Do Q".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /XObject << /Im1 4 0 R >> >> /Contents 5 0 R >>",
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
        f"/Length {len(data)} >>\nstream\n".encode()
        + data
        + b"\nendstream",
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def test_pdf_images_reads_pixels_and_placement():
    img = plot()
    pdf = one_image_pdf(img, 83.3, 214.8, 215.0, 155.0)
    images = pdf_images(pdf)
    assert len(images) == 1
    im = images[0]
    assert im.page == 1 and im.name == "/Im1"
    assert np.allclose(im.bbox, (83.3, 214.8, 298.3, 369.8))
    assert np.array_equal(im.pixels, img)
    # small images (logos) are left out
    assert pdf_images(pdf, min_pixels=img.shape[0] * img.shape[1] + 1) == []
