import pytest

from iact_perf.extract.latex import Cell, find_table, parse_cell, parse_range, split_rows

TEX = r"""
%\begin{table}
%\begin{tabular}{c|c}
%1 & 2 \\
%\end{tabular}
%\label{tab:old}
%\end{table}
\begin{table}[t]
\begin{tabular}{c|c|c}
$E [GeV]$ & bias [\%] & $\Theta_{0.68}[^\circ]$ \\\hline\hline
47 - 75 & $24.6 \pm 0.9$ & $0.157_{-0.007}^{+0.007}$ \rule{0pt}{10pt}\\[0.5ex]\hline
75 - 119 & $-0.1\pm0.3$ & $0.056_{-0.012}^{+0.062}$ \\\hline % a comment
\end{tabular}
\caption{A table.}\label{tab:a}
\end{table}
\begin{table*}
\begin{tabular*}{0.99\textwidth}{@{\extracolsep{\fill}} c|c}
63 & 17 \\ \hline
\end{tabular*}
\label{tab:b}
\end{table*}
"""


def test_find_table_and_rows():
    body = find_table(TEX, "tab:a")
    header, data = body.split(r"\hline\hline", 1)
    rows = split_rows(data)
    assert rows == [
        ["47 - 75", r"$24.6 \pm 0.9$", r"$0.157_{-0.007}^{+0.007}$"],
        ["75 - 119", r"$-0.1\pm0.3$", r"$0.056_{-0.012}^{+0.062}$"],
    ]


def test_tabular_star():
    assert split_rows(find_table(TEX, "tab:b")) == [["63", "17"]]


def test_commented_table_is_ignored():
    with pytest.raises(KeyError):
        find_table(TEX, "tab:old")


@pytest.mark.parametrize(
    "cell, expected",
    [
        (r"$24.6 \pm 0.9$", Cell(24.6, 0.9, 0.9)),
        (r"$-0.1\pm0.3$", Cell(-0.1, 0.3, 0.3)),
        (r"$0.056_{-0.012}^{+0.062}$", Cell(0.056, 0.012, 0.062)),
        (r"$0.056^{+0.062}_{-0.012}$", Cell(0.056, 0.012, 0.062)),
        ("17", Cell(17.0)),
        (r"$4200 \pm 1700$", Cell(4200.0, 1700.0, 1700.0)),
        ("1.5e-3", Cell(1.5e-3)),
    ],
)
def test_parse_cell(cell, expected):
    assert parse_cell(cell) == expected


def test_parse_cell_rejects_text():
    with pytest.raises(ValueError):
        parse_cell("n/a")


def test_parse_range():
    assert parse_range("47 - 75") == (47.0, 75.0)
    assert parse_range("11943--18928") == (11943.0, 18928.0)
