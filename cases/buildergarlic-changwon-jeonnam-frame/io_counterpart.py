"""보고서의 지역산업연관분석(참고3)에 대응하는 '가장 가까운 재현' — 창원 통합 인센티브의 기대 생산·고용 효과.

보고서는 한국은행 2020년 지역산업연관표로 20조 재정지원의 생산유발(전국 36.0조, 역내 17.0조)·고용유발(연 5조당 전국 4.4만,
역내 2.3만)을 계산했다. 시군 단위 산업연관표는 공표되지 않으므로 창원에는 같은 표를 쓸 수 없다. 대신

  (1) 레온티예프 역행렬 계산기(leontief_inverse, production_effect, employment_effect)를 두어, 한국은행 ECOS 에서 경남
      지역산업연관표(2010·2015·2020)의 투입계수 행렬 A 와 취업계수를 받아 CSV 로 넣으면 보고서와 같은 식으로 계산할 수 있게 하고,
  (2) 그 표가 없을 때는 보고서 수치에서 역산한 승수(생산 1.80/0.85, 고용 8.8/4.6명/10억원)를 창원 통합 인센티브에
      적용해 '보고서 방식으로 기대할 수 있는 효과의 크기'를 낸다(expected_effects).

이 수치는 사후 추정치가 아니라 사전 기대치이며, scorecard.py 가 실제 관측된 종사자 변화의 신뢰구간과 크기를 견주는 데 쓴다.

    python io_counterpart.py                      # 기본 가정으로 io_counterpart.json / io_counterpart.md
    python io_counterpart.py --support 3000       # 인센티브 총액(억원, 10년) 민감도
    python io_counterpart.py --A data/A_gyeongnam.csv --emp-coef data/emp_coef_gyeongnam.csv --demand data/demand.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent

# ── 보고서(한국은행 광주전남본부·목포본부 2026.7)에서 읽은 값 ──────────────────────────────────────
REPORT = {
    "support_total_tn_krw": 20.0,  # 4년 최대 20조 (¶3)
    "support_per_year_tn_krw": 5.0,  # 연 최대 5조
    "production_national_tn": 36.0,  # 전국 생산유발효과 (¶23)
    "production_region_tn": 17.0,  # 전남·광주 역내 (¶24)
    "production_gyeonggi_tn": 20.9,  # 같은 20조를 경기에 넣었을 때 역내 (참고4)
    "jobs_national": 44_000,  # 연 5조 투입 시 고용유발 (¶27)
    "jobs_region": 23_000,  # 역내
    "grdp_region_tn_2024": 158.8,  # 광주 54.8 + 전남 104.0 (¶5)
    "population_region_2025": 3_200_000,  # 광주·전남 주민등록인구 근사(2025) — 확인필요
}


def implied_multipliers(r: dict = REPORT) -> dict:
    """보고서 수치에서 역산한 승수. 생산: 원/원, 고용: 명/10억원."""
    s, y = r["support_total_tn_krw"], r["support_per_year_tn_krw"]
    return {
        "production_national": r["production_national_tn"] / s,
        "production_region": r["production_region_tn"] / s,
        "production_gyeonggi_region": r["production_gyeonggi_tn"] / s,
        "jobs_per_bn_national": r["jobs_national"] / (y * 1000),  # 1조 = 1,000 십억
        "jobs_per_bn_region": r["jobs_region"] / (y * 1000),
        "region_retention_share": r["production_region_tn"] / r["production_national_tn"],
        "gyeonggi_retention_share": r["production_gyeonggi_tn"] / 35.4,  # 참고4: 경기 전국 35.4조
    }


# ── 창원 통합 인센티브 (가정 — 확인필요) ─────────────────────────────────────────────────────────
CHANGWON = {
    "support_total_bn_krw": 1460.0,  # 억원, 10년 합계. 보통교부세 추가 교부(통합 전 3개 시 합산액의 6%, 10년) 언론 보도 기준 — 확인필요
    "support_years": 10,
    "support_note": (
        "「지방교부세법 시행령」의 통합 지방자치단체 보통교부세 추가 교부(통합 전 지자체 보통교부세 합산액의 6% 를 10년간)를 "
        "창원시에 적용한 금액으로 2010년 당시 언론·시 발표에 '10년간 약 1,460억 원'으로 보도됨. 결산서로 확인하지 못했으므로 "
        "가정이며 --support 로 바꿔 민감도를 본다. 통합 특별교부세·국고보조 등은 포함하지 않음"
    ),
}


# ── 산업연관분석 계산기 (경남 지역산업연관표를 CSV 로 넣을 때) ─────────────────────────────────
def leontief_inverse(A: np.ndarray) -> np.ndarray:
    """(I − A)⁻¹ — 생산유발계수 행렬. A 는 투입계수 행렬(열 = 산업, 각 열 합 < 1)."""
    A = np.asarray(A, float)
    if A.ndim != 2 or A.shape[0] != A.shape[1]:
        raise ValueError("A 는 정방행렬이어야 합니다")
    if (A < 0).any() or (A.sum(axis=0) >= 1).any():
        raise ValueError(
            "투입계수는 0 이상이고 각 열의 합이 1 미만이어야 합니다 (AX + Y = X 가 풀리는 조건)"
        )
    return np.linalg.inv(np.eye(len(A)) - A)


def production_effect(A: np.ndarray, y: np.ndarray) -> np.ndarray:
    """최종수요 벡터 y(부문별) → 부문별 생산유발액 X = (I − A)⁻¹ y."""
    return leontief_inverse(A) @ np.asarray(y, float)


def employment_effect(A: np.ndarray, y: np.ndarray, emp_coef: np.ndarray) -> np.ndarray:
    """고용유발 = 취업계수(명/단위 생산) × 생산유발액 (보고서 참고3: 생산유발계수에 취업계수를 적용)."""
    return np.asarray(emp_coef, float) * production_effect(A, y)


def split_8_1_1(total: float) -> dict[str, float]:
    """보고서 ¶22 의 8:1:1 원칙 — 미래 핵심산업 80%, 인재양성 10%, 사회안전망·삶의 질 10%."""
    return {"핵심산업": 0.8 * total, "인재양성": 0.1 * total, "사회안전망·삶의질": 0.1 * total}


# ── 승수 차용 방식 (표가 없을 때) ───────────────────────────────────────────────────────────────
def expected_effects(
    support_total_bn_krw: float = CHANGWON["support_total_bn_krw"],
    support_years: int = CHANGWON["support_years"],
    baseline_employees: float | None = None,
    baseline_population: float | None = None,
    report: dict = REPORT,
) -> dict:
    """창원 인센티브(억원, 총액)에 보고서의 승수를 적용한 기대 효과. 생산은 억원, 고용은 명(연간)."""
    m = implied_multipliers(report)
    per_year_bn = support_total_bn_krw / support_years  # 억원/년
    per_year_tn_won_bn = per_year_bn / 10  # 십억원/년 (고용 승수의 단위)
    out = {
        "inputs": {
            "support_total_bn_krw": support_total_bn_krw,
            "support_years": support_years,
            "support_per_year_bn_krw": per_year_bn,
        },
        "multipliers": m,
        "production_total_bn_krw": {
            "national": support_total_bn_krw * m["production_national"],
            "region": support_total_bn_krw * m["production_region"],
            "region_if_gyeonggi_like": support_total_bn_krw * m["production_gyeonggi_region"],
        },
        "jobs_per_year": {
            "national": per_year_tn_won_bn * m["jobs_per_bn_national"],
            "region": per_year_tn_won_bn * m["jobs_per_bn_region"],
        },
    }
    if baseline_employees:
        jr = out["jobs_per_year"]["region"]
        out["jobs_region_share_of_baseline_pct"] = jr / baseline_employees * 100
        out["implied_log_employment_effect"] = float(np.log1p(jr / baseline_employees))
    # 보고서 패키지와의 규모 비교 (1인당 연간 지원액)
    rp = report["support_per_year_tn_krw"] * 1e12 / report["population_region_2025"]
    out["scale_vs_report"] = {"report_support_per_capita_krw_per_year": rp}
    if baseline_population:
        cp = per_year_bn * 1e8 / baseline_population
        out["scale_vs_report"].update(
            {"changwon_support_per_capita_krw_per_year": cp, "ratio_changwon_to_report": cp / rp}
        )
    rg = report["support_per_year_tn_krw"] / report["grdp_region_tn_2024"] * 100
    out["scale_vs_report"]["report_support_share_of_grdp_pct_per_year"] = rg
    return out


def render_md(res: dict) -> str:
    m, p, j = res["multipliers"], res["production_total_bn_krw"], res["jobs_per_year"]
    s = res["scale_vs_report"]
    L = [
        "# 산업연관분석 대응 — 창원 통합 인센티브에 보고서 승수를 적용한 기대 효과",
        "",
        "> 사후 추정치가 아니라 **보고서 방식의 사전 기대치**입니다. 시군 단위 산업연관표가 없어 보고서 수치에서 역산한 승수를 차용했습니다.",
        "",
        "| 항목 | 값 | 근거 |",
        "|---|---:|---|",
        f"| 창원 통합 인센티브 (가정) | {res['inputs']['support_total_bn_krw']:,.0f}억 원 / {res['inputs']['support_years']}년 (연 {res['inputs']['support_per_year_bn_krw']:,.0f}억) | {CHANGWON['support_note']} |",
        f"| 생산유발 승수 (전국 / 역내 / 경기형 역내) | {m['production_national']:.2f} / {m['production_region']:.2f} / {m['production_gyeonggi_region']:.2f} | 보고서 36.0조·17.0조·20.9조 ÷ 20조 |",
        f"| 고용유발 승수 (전국 / 역내, 명/10억원) | {m['jobs_per_bn_national']:.1f} / {m['jobs_per_bn_region']:.1f} | 보고서 4.4만·2.3만 ÷ 연 5조 |",
        f"| 기대 생산유발 (10년 누계, 억 원) | 전국 {p['national']:,.0f} · 역내 {p['region']:,.0f} · 경기형 {p['region_if_gyeonggi_like']:,.0f} | 인센티브 × 승수 |",
        f"| 기대 고용유발 (연간, 명) | 전국 {j['national']:,.0f} · 역내 {j['region']:,.0f} | 연간 인센티브 × 승수 |",
    ]
    if "jobs_region_share_of_baseline_pct" in res:
        L.append(
            f"| 역내 고용유발 ÷ 통합 직전 창원 종사자수 | {res['jobs_region_share_of_baseline_pct']:.3f}% (로그 효과 ≈ {res['implied_log_employment_effect']:.5f}) | 패널의 2009년 값 |"
        )
    L.append(
        f"| 보고서 패키지의 규모 | 1인당 연 {s['report_support_per_capita_krw_per_year']:,.0f}원, GRDP 대비 연 {s['report_support_share_of_grdp_pct_per_year']:.1f}% | 연 5조 ÷ 인구 약 320만·GRDP 158.8조 |"
    )
    if "changwon_support_per_capita_krw_per_year" in s:
        L.append(
            f"| 창원 인센티브의 규모 | 1인당 연 {s['changwon_support_per_capita_krw_per_year']:,.0f}원 (보고서의 {s['ratio_changwon_to_report'] * 100:.1f}%) | 연 인센티브 ÷ 2011년 주민등록인구 |"
        )
    L += [
        "",
        "**읽는 법.** 보고서의 정량 효과는 GRDP 의 10%를 넘는 재정 패키지에서 나옵니다. 창원 통합의 재정 인센티브는 보고서식으로 계산해도 "
        "역내 고용유발이 연 수십 명 수준이라, 통합 후 창원의 종사자·사업체 변화가 있었다면 그것은 '재정지원 경로'가 아니라 "
        "행정 효율화·산업 구조 경로에서 나온 것으로 읽어야 합니다. 같은 이유로 이 케이스의 사후 추정(신뢰구간 폭 수 %p)으로는 "
        "재정 경로의 효과(0.0x%)를 검출할 수 없습니다 — 검출 못 함이 곧 효과 없음은 아닙니다.",
        "",
        "경남 지역산업연관표(한국은행 ECOS)의 투입계수 행렬과 취업계수를 CSV 로 넣으면 `--A/--emp-coef/--demand` 로 보고서와 같은 "
        "(I − A)⁻¹ 계산을 할 수 있습니다(`leontief_inverse`, `employment_effect`).",
    ]
    return "\n".join(L) + "\n"


def main(argv=None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--support",
        type=float,
        default=CHANGWON["support_total_bn_krw"],
        help="인센티브 총액(억원)",
    )
    ap.add_argument("--years", type=int, default=CHANGWON["support_years"])
    ap.add_argument("--A", help="투입계수 행렬 CSV (정방, 헤더 없음)")
    ap.add_argument("--emp-coef", help="취업계수 벡터 CSV (명/단위 생산)")
    ap.add_argument("--demand", help="부문별 최종수요 벡터 CSV")
    a = ap.parse_args(argv)
    baseline_emp = baseline_pop = None
    panel = HERE / "data" / "panel.csv"
    if panel.exists():
        d = pd.read_csv(panel)
        cw = d[(d["treated"] == 1)].set_index("year")
        if 2009 in cw.index:
            baseline_emp = float(cw.loc[2009, "employees"])
        if 2011 in cw.index:
            baseline_pop = float(cw.loc[2011, "population"])
    res = expected_effects(a.support, a.years, baseline_emp, baseline_pop)
    if a.A and a.emp_coef and a.demand:
        A = np.loadtxt(a.A, delimiter=",")
        y = np.loadtxt(a.demand, delimiter=",")
        c = np.loadtxt(a.emp_coef, delimiter=",")
        res["io_table_run"] = {
            "production_by_sector": production_effect(A, y).tolist(),
            "employment_by_sector": employment_effect(A, y, c).tolist(),
        }
    (HERE / "io_counterpart.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), "utf-8"
    )
    (HERE / "io_counterpart.md").write_text(render_md(res), "utf-8")
    print(render_md(res))


if __name__ == "__main__":
    main()
