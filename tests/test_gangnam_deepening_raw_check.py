"""독립 CSV 검사에서 마지막 행 손상과 숫자 0·미수록을 구별한다."""

import csv
import io
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
from gangnam.deepening_raw_check import expected_header, lookup, scan_archive


def test_independent_reader_checks_width_after_first_row(tmp_path):
    text = io.StringIO()
    writer = csv.writer(text)
    header = expected_header("bus_trips")
    writer.writerow(header)
    writer.writerow(["20240822", "r", "s", "0", *["0"] * 24, "1"])
    writer.writerow(["20240822", "r", "s", "0"])
    path = tmp_path / "broken.zip"
    with ZipFile(path, "w") as z:
        z.writestr("weekly.csv", text.getvalue().encode("cp949"))
    with pytest.raises(ValueError, match="행 너비"):
        scan_archive(path, "bus_trips", ["2024-08-22"], {"r"}, {"s"})


def test_raw_zero_blank_absence_and_repeated_stop_are_distinct():
    records = {("day", "r", "s", ""): {(('1',), tuple([0., None] + [1.] * 22))}}
    key = ("day", "r", "s", "")
    assert lookup(records, key, 0) == ("zero", 0.)
    assert lookup(records, key, 1) == ("blank", None)
    assert lookup(records, ("other", "r", "s", ""), 0) == ("row_absent", None)
    records[key].add((('2',), tuple([2.] * 24)))
    assert lookup(records, key, 0) == ("multiple_records_quarantined", None)
