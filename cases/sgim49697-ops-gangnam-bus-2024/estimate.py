"""개인 사례의 전후 비교·주별 격차·민감도를 생성한다. make flow와 별도 경로다."""

from __future__ import annotations

import argparse

import pandas as pd
from gangnam.common import CASE, holiday_dates, read_yaml, real_data_gate, write_json
from gangnam.policy import build_panel, diagnostics, sensitivities
from gangnam.topis import read_hourly


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weather", help="weather.py로 검증한 일별 CSV")
    args = parser.parse_args()
    registration = real_data_gate()
    cfg = read_yaml("corridors.yaml")
    hourly = read_hourly(CASE / "data/processed", verify=True)
    days = holiday_dates(cfg["pre"][0], cfg["post"][1])
    panel, quality = build_panel(hourly, cfg, days)
    out = CASE / "runs/policy"
    out.mkdir(parents=True, exist_ok=True)
    result = {"registration": registration, "quality": quality, "verdict": "not_identified"}
    if quality["comparative"]:
        weather = None
        if args.weather:
            from gangnam.weather import load_verified_weather
            weather = load_verified_weather(args.weather)
        result.update(diagnostics(panel, cfg))
        result["sensitivities"] = sensitivities(hourly, cfg, days, quality["selected_controls"], weather)
    else:
        result["note"] = "비교 도로 또는 동일 날짜 부족. 도로별 기술통계만 제공"
    panel.assign(period=panel.date.ge(cfg["policy_date"]).map({True: "post", False: "pre"})).groupby(
        ["corridor_id", "period"]).speed_index.agg(["count", "mean", "std"]).to_csv(out / "descriptive.csv")
    write_json(out / "diagnostics.json", result)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for name, data in panel.groupby("corridor_id"):
        plt.plot(data.date, data.speed_index, label=name, alpha=0.75)
    plt.axvline(pd.Timestamp(cfg["policy_date"]), color="black", linestyle="--")
    plt.ylabel("Fixed length-weighted speed index (km/h)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out / "daily_speed.png", dpi=160)
    plt.close()
    (out / "report.md").write_text(
        "# 강남대로 정책 전후 비교\n\n판정: **not_identified**. 처치 도로는 1곳이다.\n\n"
        + (f"동일 날짜 패널의 이중차분: {result['did_kmh']:.3f} km/h.\n\n" if "did_kmh" in result else "비교 설계 기준 미달.\n\n")
        + "주별 격차·가짜 시점·비교군 제외·기간 민감도는 diagnostics.json을 참고한다. "
        "동시 정책·장마·우회 노출을 배제하지 못하므로 정책 인과효과나 버스 승객 시간 절감으로 해석하지 않는다.\n",
        encoding="utf-8")
    print(f"생성 완료: {out}. 공개 전 이용 조건과 작성자 해석을 검토하세요.")


if __name__ == "__main__":
    main()
