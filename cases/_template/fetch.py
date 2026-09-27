"""② 수집 — 공공데이터를 받아 분석용 표 data/panel.csv 를 만듭니다.

`make flow CASE=cases/<내ID>-<주제>` 가 이 파일을 먼저 실행하고, data/panel.csv 가 생기면 다음 단계로 갑니다.
한 행 = 단위(예: 시군구) × 시점(예: 월). plan.yaml 의 unit.id_col, time.col, treatment.group_col,
outcomes[].col 에 적은 열 이름이 모두 있어야 합니다.

참고 예시
- cases/t3-land-permit-2025/fetch.py : 국토부 실거래가 API(키가 없으면 시뮬레이션)로 구×월 패널 만들기
- core/adapters/ : 공공데이터포털·KOSIS·법제처 수집기 (키는 .env 에, 커밋 금지)

주의: data/ 아래 파일은 git에 올라가지 않습니다(.gitignore). 데이터는 이 스크립트로 누구나 다시 받게 합니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "panel.csv"


def build_panel() -> pd.DataFrame:
    # TODO: 여기서 데이터를 받아 정리합니다. 예)
    #   from core.adapters.molit import MolitAptTradeAdapter
    #   raw = MolitAptTradeAdapter().fetch(...)
    #   panel = raw.groupby(["region_id", "month_idx"]).agg(...).reset_index()
    #   panel["treated"] = panel["region_id"].isin(TREATED).astype(int)
    raise NotImplementedError


def main() -> None:
    try:
        panel = build_panel()
    except NotImplementedError:
        sys.exit(
            "fetch.py 의 build_panel() 을 아직 채우지 않았습니다. "
            "공공데이터를 받아 data/panel.csv 를 만드는 코드를 적어 주세요 (예시: cases/t3-land-permit-2025/fetch.py)."
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(OUT, index=False)
    print(f"[fetch] {len(panel)}행 → {OUT.relative_to(HERE)}")


if __name__ == "__main__":
    main()
