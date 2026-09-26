# [예제] 달빛어린이병원 × 소아 야간 경증 응급실 방문 — DiD / Event study

> ## ⚠️ 이 케이스의 데이터는 **합성(synthetic)** 입니다
> `core.adapters.synthetic.simulate_panel` 로 만든 가짜 시군구 패널(80개 지역, 2012–2019,
> 30개 지역 2016년 동시 지정, **참효과 = -5.0**)입니다. 결과 수치는 실제 정책 효과가 **아니며**,
> 파이프라인(plan → fetch → estimate → report)이 참값을 복원하는지 보여주는 시연용입니다.

## 실행
```bash
python cases/_example_night_clinic/fetch.py      # data/panel.csv (+ panel.source.json)
python cases/_example_night_clinic/estimate.py   # figures/*.png, report.md, results.json
```

## 파일
| 파일 | 역할 |
|---|---|
| `plan.yaml` | 분석계획: 질문·처치/통제·결과변수·가정·반박검정·**보류 조건** (`core/schema/plan.py` 로 검증) |
| `fetch.py` | 데이터 수집 → `data/` 스냅샷 + 출처 JSON |
| `estimate.py` | `core.pipeline.run_plan` 실행 + 보조 DiD + 그림 + 리포트 |
| `report.md` | 자동 생성 리포트 (판정·경고가 수치보다 먼저) |

## 우리 조 케이스로 바꾸려면
1. 이 폴더를 `cases/<조이름>_<주제>/` 로 복사 (또는 `cases/_template/` 사용)
2. `plan.yaml` 을 먼저 쓴다 — 특히 `control.rationale` 과 `abstention` 은 데이터 보기 **전에** 확정
3. `fetch.py` 를 실데이터 어댑터로 교체하고 `synthetic_data: false`, `data_sources.license` 를 공공누리 유형으로
4. 실제 지정 시점이 지역마다 다르면 `treatment.first_treat_col` 사용 → 시차도입 경고가 뜨는 것이 정상.
   이 경우 TWFE 결과는 `not_identified` 로 보류되며, Callaway–Sant'Anna 추정이 필요합니다(멘토 논의).

## 해볼 것 (W6 과잉해석 방지 실습)
`fetch.py` 의 `simulate_panel(..., pretrend_slope=1.5, effect=0)` 로 바꿔 다시 실행해 보세요.
효과가 "유의하게" 나오더라도 사전추세 검정이 기각되어 판정이 **식별 불가**로 바뀝니다.
