"""끝점 이름 허용이 길이·방향이 바뀐 링크까지 포함하지 않는지 검증한다."""

import importlib
import sys
from pathlib import Path

import pandas as pd

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
names = importlib.import_module("gangnam.overnight_road_names")


def test_only_names_can_change():
    rows = [("a", "도로", "상행", 100, "옛이름"), ("a", "도로", "상행", 100, "새이름"),
            ("b", "도로", "상행", 100, "같음"), ("b", "도로", "상행", 200, "같음"),
            ("c", "도로", "상행", 100, "같음"), ("c", "도로", "하행", 100, "같음")]
    data = pd.DataFrame(rows, columns=["링크아이디", "도로명", "방향", "거리", "시점명"])
    kept, removed = names.relaxed_metadata(data, ["도로명", "방향", "거리"])
    assert kept.link_id.tolist() == ["a"]
    assert removed == ["b", "c"]
