"""개통 경계와 공란·상충 날짜를 별도 Pandas CSV 판독으로 대조한다."""

import json
from zipfile import ZipFile

import pandas as pd

from .common import CASE, sha256, utcnow, write_json
from .deepening_infrastructure import OUT


def run():
    # 전체 상태를 본 뒤 정한 확인 날짜이며 새 분석 기간 또는 효과 선택이 아니다.
    dates = ['20250109', '20250110', '20250111', '20250125', '20250126', '20250203']
    selected = {"2025-01": ['tpss_sta_route_hturn_2025.01.06-01.12.csv', 'tpss_sta_route_hturn_2025.01.20-01.26.csv'],
                "2025-02": ['tpss_sta_route_hturn_2025.02.03-02.09.csv']}
    audit_path = OUT / "trip_support_audit.json"
    audit = json.loads(audit_path.read_text())
    path = OUT / "trip_support_daily.csv"
    if sha256(path) != audit["outputs"][path.name]:
        raise ValueError("운행 경계 검증의 출력 해시 변경")
    daily = pd.read_csv(path, dtype={"node": str, "route": str})
    daily = daily[daily.date.str.replace("-", "").isin(dates)]
    pieces, source_dates, scanned = [], set(), 0
    for source in audit["sources"]:
        if sha256(CASE / source["path"]) != source["sha256"]:
            raise ValueError("운행 경계 검증의 원본 해시 변경")
        with ZipFile(CASE / source["path"]) as archive:
            for member in selected[source["month"]]:
                with archive.open(member) as stream:
                    for chunk in pd.read_csv(stream, encoding="cp949", dtype=str, chunksize=100000):
                        scanned += len(chunk)
                        source_dates.update(chunk["기준_날짜"])
                        mask = chunk["기준_날짜"].isin(dates) & chunk["노선_ID"].isin(daily.route) & chunk["정류장_ID"].isin(daily.node)
                        pieces.append(chunk[mask].copy())
    raw = pd.concat(pieces, ignore_index=True)
    hour_columns = [f"버스운행횟수_{hour:02}시" for hour in range(24)]
    for column in ["버스운행횟수", *hour_columns]:
        raw[column] = pd.to_numeric(raw[column], errors="raise")
    raw = raw.drop_duplicates()
    grouped = {key: part for key, part in raw.groupby(["기준_날짜", "노선_ID", "정류장_ID"])}
    checks = 0
    for row in daily.itertuples(index=False):
        day = row.date.replace("-", "")
        part = grouped.get((day, row.route, row.node))
        values = dict(positive_hours=0, zero_hours=0, negative_hours=0, blank_hours=0, unavailable_hours=24)
        if day not in source_dates:
            state = "source_date_absent"
        elif part is None:
            state = "row_absent"
        elif len(part) > 1:
            state = "multiple_records_quarantined"
        else:
            state = "unique_record"
            hours = part[hour_columns].iloc[0]
            values = dict(positive_hours=int(hours.gt(0).sum()), zero_hours=int(hours.eq(0).sum()),
                          negative_hours=int(hours.lt(0).sum()), blank_hours=int(hours.isna().sum()), unavailable_hours=0)
        if state != row.record_state or any(getattr(row, key) != value for key, value in values.items()):
            raise ValueError(f"별도 판독의 운행 상태 불일치: {row.date}, {row.route}, {row.node}")
        checks += len(values)
    write_json(OUT / "trip_support_validation.json", dict(completed_at=utcnow(), code_sha256=sha256(__file__),
        audit_sha256=sha256(audit_path), dates=dates, members=selected, raw_rows_scanned=scanned,
        route_stop_days=len(daily), state_checks=len(daily), numeric_checks=checks, mismatches=0,
        scope="원본 3개 주간 파일에서 개통 전후·전체 공란·재방문/상충 경계를 별도 판독, 전체 기간 재검증은 아님"))
    print(f"운행 경계 별도 판독: {len(daily)}개 상태·{checks}개 수치 일치", flush=True)
