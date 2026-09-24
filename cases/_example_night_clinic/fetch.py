"""데이터 수집 단계 — 이 예제는 합성 데이터를 생성한다 (⚠️ 실데이터 아님).

실데이터로 바꿀 때는 아래 `fetch_real()` 처럼 core.adapters 의 어댑터를 쓰고,
plan.yaml 의 synthetic_data / data_sources 를 함께 수정하세요.

실행: python cases/_example_night_clinic/fetch.py
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # 패키지 설치 전에도 실행되도록

from core.adapters import KosisAdapter, SyntheticAdapter  # noqa: E402

TRUE_EFFECT = -5.0


def fetch_synthetic():
    ad = SyntheticAdapter()
    q = dict(
        n_units=80, n_treated=30, start=2012, end=2019, treat_time=2016, effect=TRUE_EFFECT, seed=42
    )
    df = ad.fetch(**q).rename(columns={"y": "night_ed_rate"})
    return ad.save(df, HERE / "data" / "panel.csv", q)


def fetch_real():  # 참고용: KOSIS_API_KEY 필요, 네트워크 필요
    """예: 시군구별 0~14세 주민등록인구(분모). 통계표 ID 는 KOSIS 에서 확인 후 수정."""
    ad = KosisAdapter()
    q = dict(
        orgId="101",
        tblId="DT_1B04005N",
        itmId="T2",
        objL1="ALL",
        prdSe="Y",
        startPrdDe="2012",
        endPrdDe="2019",
    )
    return ad.save(ad.fetch(**q), HERE / "data" / "raw_population.csv", q)


if __name__ == "__main__":
    print("saved:", fetch_synthetic())
