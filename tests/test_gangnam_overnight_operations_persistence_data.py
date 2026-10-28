"""새 승차 원본의 비선택 행 손상도 발견하며 공란·0·음수를 구별하는지 검사한다."""

import csv
import importlib
import io
import sys
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.overnight_operations_persistence_data")


def archive(tmp_path, rows):
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow([*module.KEYS, "승차_승객_수_17시", "승차_승객_수_18시", "승차_승객_수_19시"])
    writer.writerows(rows)
    path = tmp_path / "source.zip"
    with ZipFile(path, "w") as output:
        output.writestr("week.csv", text.getvalue().encode("cp949"))
    return path


def test_selected_counts_preserve_blank_zero_negative_and_full_source_dates(tmp_path):
    path = archive(tmp_path, [["20250501", "r", "s", "1", "", "0", "-1"], ["20250502", "r", "x", "2", "1", "2", "3"]])
    result, dates, total, members = module.read_archive(path, {"s"}, [17, 18, 19])
    assert len(result) == 1 and total == 2
    assert pd.isna(result.loc[0, "h17"]) and result.loc[0, "h18"] == 0 and result.loc[0, "h19"] == -1
    assert dates == ["20250501", "20250502"]
    assert members[0]["rows_scanned"] == 2


def test_unselected_malformed_row_cannot_pass_column_projection(tmp_path):
    path = archive(tmp_path, [["20250501", "r", "s", "1", "1", "2", "3"], ["20250502", "r", "x", "2", "1", "2"]])
    with pytest.raises(ValueError, match="행 길이"):
        module.read_archive(path, {"s"}, [17, 18, 19])
