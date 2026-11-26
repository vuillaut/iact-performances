"""Read histograms and macros from ROOT files held in memory (needs ``uproot``)."""

from __future__ import annotations

import io

import numpy as np


class RootFile:
    """A ROOT file read from bytes: ``RootFile(data)["DiffSens"]`` -> (values, edges)."""

    def __init__(self, data: bytes, name: str = "<memory>"):
        import uproot

        self.name = name
        self._file = uproot.open(io.BytesIO(data))

    def keys(self) -> list[str]:
        return sorted(self._file.keys(cycle=False))

    def __contains__(self, key: str) -> bool:
        return key in self._file

    def histogram(self, key: str) -> tuple[np.ndarray, ...]:
        """``(values, *edges)`` of a histogram, without under/overflow bins."""
        if key not in self._file:
            raise KeyError(f"{key} not in {self.name}")
        return self._file[key].to_numpy()

    def title(self, key: str) -> str:
        obj = self._file[key]
        return str(obj.member("fTitle")) if hasattr(obj, "member") else ""

    def axis_title(self, key: str, axis: str = "x") -> str:
        return str(self._file[key].axis(axis).member("fTitle"))

    def macro(self, key: str) -> str:
        """Text of a ``TMacro`` (one line per entry)."""
        lines = self._file[key].member("fLines")
        return "\n".join(str(line) for line in lines)  # TObjString is a str

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> RootFile:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
