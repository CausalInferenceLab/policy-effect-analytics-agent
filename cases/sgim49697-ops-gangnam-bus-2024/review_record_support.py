# review_record_support.py - 남행 저녁 정책 후보 노선과 고정 13·14개 노선의 양수 기록 비율을 정의 고정 표로 만든다.
"""첫 종합의 94.4→25.2% 수치를 같은 정의(원본 날짜가 있는 날 분모)로 재현하고 고정 노선과의 겹침을 확인한다."""

import argparse
import csv
import io
from pathlib import Path

import yaml

CASE = Path(__file__).resolve().parent
SOURCE = "results/overnight/bus/missingness_by_route_segment.csv"
ROUTES = "overnight_matched_directions_config.yaml"
OUTPUT = "results/deepening/review/record_support.csv"
SELECTION = {"cohort": "common_pre_source_days", "band": "evening", "group": "central_south"}
PERIODS = ["pre2024", "post2024"]
FIELDS = ["group", "period", "routes", "policy_candidate_routes", "expected_cells", "source_date_absent", "positive",
          "positive_fraction_source_dates", "positive_fraction_all_cells"]
COUNTS = ["expected_cells", "source_date_absent", "positive"]


def derive(base=CASE):
    with (base / SOURCE).open(encoding="utf-8", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if all(row[key] == value for key, value in SELECTION.items())]
    retained = set(yaml.safe_load((base / ROUTES).read_text(encoding="utf-8"))["expected_common_routes"])
    if len(retained) != 14 or not rows:
        raise ValueError("고정 14개 노선 또는 남행 저녁 기록이 없습니다")
    groups = {"policy_candidate": lambda row: row["policy_group"] != "other_or_unclassified",
              "other_or_unclassified": lambda row: row["policy_group"] == "other_or_unclassified",
              "retained_14": lambda row: row["route"] in retained}
    result = []
    for name, chosen in groups.items():
        for period in PERIODS:
            part = [row for row in rows if row["period"] == period and chosen(row)]
            if not part:
                raise ValueError(f"기록 지원 표의 빈 집단: {name} {period}")
            total = {key: sum(int(row[key]) for row in part) for key in COUNTS}
            available = total["expected_cells"] - total["source_date_absent"]
            if available <= 0:
                raise ValueError("원본 날짜가 있는 분모가 없습니다")
            routes = {row["route"] for row in part}
            result.append(dict(group=name, period=period, routes=len(routes),
                policy_candidate_routes=len({row["route"] for row in part if row["policy_group"] != "other_or_unclassified"}),
                positive_fraction_source_dates=total["positive"] / available,
                positive_fraction_all_cells=total["positive"] / total["expected_cells"], **total))
    return result


def table(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    group = cli.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = cli.parse_args()
    content = table(derive())
    path = CASE / OUTPUT
    if args.write:
        path.write_bytes(content)
    elif path.read_bytes() != content:
        raise ValueError("저장된 기록 지원 표가 현재 원자료와 다릅니다")
    print("남행 저녁 기록 지원 표 " + ("작성" if args.write else "대조 통과"))
