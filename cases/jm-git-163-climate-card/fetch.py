"""개인 저장소의 고정된 도시×월 스냅샷을 멘토 형식 data/panel.csv로 받는다.

원자료 정리 코드는 개인 저장소 src/prepare.py, src/prepare_cities.py에 공개되어 있다.
공공데이터포털 파일은 기관별 형식과 과거 첨부파일 선택이 달라 한 번에 자동 다운로드하기
어렵기 때문에, 공용 저장소에서는 검증된 가공 스냅샷을 고정 커밋에서 내려받는다.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

HERE = Path(__file__).resolve().parent
COMMIT = "0be85dc31425a317c451727e4715af7df28c0d72"
SNAPSHOT_URL = (
    "https://raw.githubusercontent.com/jm-git-163/subway-did-climate-card/"
    f"{COMMIT}/data/processed/city_month.csv"
)
EXPECTED_CITIES = {"seoul", "busan", "daegu", "gwangju", "daejeon"}
REQUIRED = ["city", "month", "month_idx", "treated", "log_weekday", "log_weekend"]


def main() -> None:
    with urlopen(SNAPSHOT_URL, timeout=60) as response:
        payload = response.read()

    panel = pd.read_csv(io.BytesIO(payload))
    missing = [column for column in REQUIRED if column not in panel.columns]
    if missing:
        raise ValueError(f"스냅샷에 필요한 열이 없습니다: {missing}")

    panel = panel[REQUIRED].copy()
    cities = set(panel["city"].unique())
    if cities != EXPECTED_CITIES:
        raise ValueError(f"도시 구성이 다릅니다: {sorted(cities)}")
    if panel.duplicated(["city", "month_idx"]).any():
        raise ValueError("도시×월 중복 행이 있습니다")
    counts = panel.groupby("city")["month_idx"].nunique()
    if not counts.eq(21).all():
        raise ValueError(f"도시별 월 수가 21개가 아닙니다: {counts.to_dict()}")

    out_dir = HERE / "data"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "panel.csv"
    panel.sort_values(["city", "month_idx"]).to_csv(out, index=False)

    meta = {
        "source": SNAPSHOT_URL,
        "source_commit": COMMIT,
        "download_sha256": hashlib.sha256(payload).hexdigest(),
        "rows": len(panel),
        "cities": sorted(cities),
        "note": "원자료 재구축 절차는 개인 저장소 README와 src/prepare_cities.py 참고",
    }
    out.with_suffix(".source.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"패널 저장: {out.relative_to(HERE)} ({len(panel)}행, 도시 {len(cities)}곳)")


if __name__ == "__main__":
    main()
