"""대형 환승 원본에서 파일 중간 손상과 헤더만 있는 날짜를 놓치지 않는지 검증한다."""

import csv
import importlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
probe = importlib.import_module("gangnam.overnight_transfer_probe")


def test_mixed_file_encodings_require_exact_known_headers():
    for encoding in ["cp949", "utf-8-sig"]:
        raw = (",".join(probe.TRANSFER) + "\n").encode(encoding)
        assert probe.header_encoding(raw, probe.TRANSFER) == encoding
    with pytest.raises(ValueError, match="공식 헤더"):
        probe.header_encoding("알 수 없는 열\n".encode(), probe.TRANSFER)


def stream(rows):
    s = io.StringIO()
    csv.writer(s).writerows(rows)
    s.seek(0)
    return s


def test_probe_preserves_ordered_ids_and_distinguishes_empty_day():
    header = ["date", "from", "to", "count"]
    output = io.StringIO()
    result = probe.scan_member(stream([header, ["20240501", "0150", "123456789", "0"],
                                       ["20240501", "0150", "0160", "3"]]), header, "20240501",
                               {"123456789"}, csv.writer(output))
    assert result["rows"] == 2 and result["selected_rows"] == 1
    assert result["id_length_pair_counts"] == {"4_9": 1, "4_4": 1}
    assert list(csv.reader(io.StringIO(output.getvalue())))[0] == ["20240501", "0150", "123456789", "0"]
    empty = probe.scan_member(stream([header]), header, "20240502", {"123456789"}, csv.writer(io.StringIO()))
    assert empty["status"] == "header_only" and empty["rows"] == 0


@pytest.mark.parametrize("bad, message", [(["20240501", "0150"], "행 너비"),
                                           (["20240502", "0150", "123456789", "1"], "실제 날짜")])
def test_probe_checks_rows_after_valid_first_record(bad, message):
    header = ["date", "from", "to", "count"]
    rows = [header, ["20240501", "0150", "123456789", "1"], bad]
    with pytest.raises(ValueError, match=message):
        probe.scan_member(stream(rows), header, "20240501", {"123456789"}, csv.writer(io.StringIO()))
