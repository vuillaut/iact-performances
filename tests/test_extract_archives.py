"""Zenodo archive walking, ROOT reading and the Eventdisplay reader, on synthetic files."""

import io
import tarfile
import zipfile

import astropy.units as u
import numpy as np
import pytest

from iact_perf.extract.zenodo import iter_archive

uproot = pytest.importorskip("uproot")

from iact_perf.extract.eventdisplay import HISTOGRAMS, as_float32_text, read_curve  # noqa: E402
from iact_perf.extract.root import RootFile  # noqa: E402

LOG_EDGES = np.round(np.arange(-1.9, 2.31, 0.2), 6)  # 21 bins, five per decade


def _tar(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_iter_archive_walks_tarballs_in_zip(tmp_path):
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("bundle/README.md", "readme")
        zf.writestr("bundle/root/a.tar.gz", _tar({"x/one.root": b"1", "x/two.txt": b"2"}))
        zf.writestr("bundle/root/b.tar.gz", _tar({"three.root": b"3"}))
    got = dict(iter_archive(path, lambda base: base.endswith(".root")))
    assert got == {"bundle/root/a.tar.gz/x/one.root": b"1", "bundle/root/b.tar.gz/three.root": b"3"}
    assert dict(iter_archive(path, lambda base: base == "README.md")) == {
        "bundle/README.md": b"readme"
    }


def _th1(values, title, axis_title):
    from uproot.writing.identify import to_TAxis, to_TH1x

    values = np.asarray(values, dtype=np.float32)
    n = len(values)
    data = np.concatenate([[0], values, [0]]).astype(">f4")
    axis = to_TAxis("xaxis", axis_title, n, float(LOG_EDGES[0]), float(LOG_EDGES[n]))
    return to_TH1x(
        "h",
        title,
        data,
        fEntries=float(n),
        fTsumw=0.0,
        fTsumw2=0.0,
        fTsumwx=0.0,
        fTsumwx2=0.0,
        fSumw2=np.zeros(n + 2, dtype=">f8"),
        fXaxis=axis,
    )


@pytest.fixture
def root_file(tmp_path):
    sens = np.geomspace(1e-11, 1e-13, 21)
    sens[0] = 0  # empty bin: no value
    path = tmp_path / "irf.root"
    with uproot.recreate(path) as f:
        f["DiffSens"] = _th1(sens, "Diff. Sens.", "log_{10} (E/TeV)")
        f["AngResEtrue"] = _th1(np.full(21, 0.055), "Ang. res.", "log_{10} (E_{MC}/TeV)")
        f["AngRes"] = _th1(np.full(21, 0.05), "Ang. res.", "log_{10} (E_{MC}/TeV)")
        f["ERes"] = _th1(np.full(21, 0.1), "E res", "log_{10} (E/TeV)")
    return RootFile(path.read_bytes(), "irf.root")


HIST = {h.key: h for h in HISTOGRAMS}


def test_read_curve(root_file):
    with root_file as f:
        curve = read_curve(f, HIST["DiffSens"])
        cols = curve["columns"]
        assert curve["n_empty"] == 1 and len(cols["value"]) == 20
        assert cols["value"].unit == u.Unit("erg cm-2 s-1")
        np.testing.assert_allclose(cols["energy_min"][0].to_value(u.TeV), 10**-1.7, rtol=1e-5)
        assert curve["energy_type"] == "reconstructed"
        assert read_curve(f, HIST["AngResEtrue"])["energy_type"] == "true"
        assert read_curve(f, HIST["BGRatePerSqDeg"]) is None  # absent


def test_energy_type_must_come_from_somewhere(root_file):
    with root_file as f:
        with pytest.raises(ValueError, match="give the energy type"):
            read_curve(f, HIST["ERes"])
        assert read_curve(f, HIST["ERes"], "true")["energy_type"] == "true"
        # AngRes is expected in reconstructed energy: a file saying otherwise fails
        with pytest.raises(ValueError, match="axis says true"):
            read_curve(f, HIST["AngRes"])


def test_float32_values_are_written_short():
    np.testing.assert_array_equal(
        as_float32_text(np.float32([0.055, 2.4975e-13])), [0.055, 2.4975e-13]
    )
