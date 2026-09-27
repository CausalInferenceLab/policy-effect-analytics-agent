# 분석 계획(plan.yaml) 작성 가이드

> 원칙: **데이터를 열기 전에** 확정하고 커밋합니다(사전 등록). `make flow`는 plan.yaml이 커밋되어 있지 않으면 계산하지 않습니다.
> 결과를 본 뒤 계획을 바꿨다면 커밋 메시지와 `discussion.md`에 무엇을, 왜 바꿨는지 적습니다.
> 칸의 정의는 `core/schema/plan.py`에 있고, 정의되지 않은 칸을 쓰면 검증 오류가 납니다. 이 문서는 **칸마다 무엇을 적어야 하는지**를 설명합니다.
> 칸 구성은 미국 GSA OES 분석 계획서(Analysis Plan)의 섹션을 따릅니다.

## 1. 칸과 결정 기준

| 칸 | 내가 정할 것 | 최소 기준 |
|---|---|---|
| `case_id` | 폴더 이름과 같게 | `<내ID>-<주제>` (예: `gildong-local-currency`). 다르면 `make flow`가 멈춥니다 |
| `question` | 한 문장의 인과 질문 | "누구의 무엇이, 어떤 정책 뒤에, 받지 않은 곳과 비교해 달라졌나" |
| `synthetic_data` | 시뮬레이션인지 | 실데이터면 `false`. `true`면 사이트에 "시뮬레이션" 표시가 붙습니다 |
| `unit`, `time` | 한 행 = 단위 × 시점 | 처치가 정해지는 단위(예: 시군구)와 같거나 더 크게. 사전 시점은 넉넉히(월이면 8개 이상 권장) |
| `treatment` | 누가, 언제 | `group_col`(0/1)과 `treat_time`. 시작일은 공식 발표·고시로 확인하고, 발표일과 시행일이 다르면 둘 다 `definition`에 적습니다 |
| `control` | 비교 대상과 그 이유 | "정책이 없었다면"을 대신 보여 줄 이유(`rationale`). 옆 지역으로 효과가 번질 곳은 빼거나 표시합니다 |
| `outcomes` | 1차 결과 1개(`primary: true`) + 2차 몇 개 | 분자·분모·기간까지. 예상 방향(`expected_direction`) |
| `estimator` | 방법 | `did` · `event_study` · `its` 중 하나. 시차 도입은 4주차, 합성통제는 5주차에 모듈이 추가됩니다 |
| `assumptions` | 식별 가정 | 가정마다 확인 방법(`check`: `pretrend_test` · `placebo_time` · `manual`) |
| `refutations` | 반증 테스트 | `placebo_time`(가짜 시작일), `placebo_outcome`, `drop_unit` 중 하나 이상 |
| `abstention` | 판정을 낮출 조건 | 기계가 판정할 수 있는 조건만(아래 표). 걸리면 효과 수치 대신 "조건부" 또는 "판단 불가" |
| `thresholds` | 기준값 | 사전추세 유의수준, 최소 클러스터 수, 최소 사전 기간 |
| `data_sources` | 데이터 출처 | 기관, URL, **라이선스**(공공누리 유형), 어댑터 |

### 판정을 낮추는 조건 (`abstention.when`)

| 조건 | 뜻 | 보통 쓰는 판정 |
|---|---|---|
| `pretrend_rejected` | 정책 전 추세가 나란하지 않음 (결합검정 p < `pretrend_alpha`) | `not_identified` |
| `placebo_significant` | 가짜 시작일에서도 효과가 보임 | `conditional` |
| `ci_crosses_zero` | 신뢰구간이 0을 포함 ("효과 없음"이 아니라 "불확실") | `conditional` |
| `few_clusters` | 단위 수가 `min_clusters`보다 적음 | `conditional` |
| `few_treated_clusters` | 정책 받은 곳이 10곳 미만 → 무작위화 추론으로 자동 전환 | `conditional` |
| `staggered_adoption` | 시작일이 여러 개인데 단순 이중차분 사용 | `not_identified` |
| `short_pre_period` | 사전 기간이 짧음 | `conditional` |

판단 불가는 실패가 아닙니다. `discussion.md`에 무엇 때문에 판단할 수 없었고, 어떤 데이터가 있으면 판단할 수 있는지 적습니다.

### 가정과 확인 방법 (자주 쓰는 것)

| 가정 | 확인 | 합격 기준 예시 |
|---|---|---|
| 평행 추세 | 이벤트 스터디 사전 계수의 결합검정 + 그림 | 결합 p ≥ 0.10 |
| 미리 반응하지 않음 | 발표일 기준과 시행일 기준 비교, 가짜 시작일 | 발표~시행 사이 계수가 유의하지 않음 |
| 옆으로 번지지 않음 | 인접 지역을 빼고 다시 추정 | 추정치가 크게 바뀌지 않음 |
| 같은 시기 다른 정책 없음 | 주제 페이지의 "관련 법령·행정규칙" 목록에서 같은 시기 개정 확인 | 있으면 기간을 빼거나 한계로 기록 |

---

## 2. 예시: 토지거래허가구역 확대 지정 (검증을 통과하는 실제 파일)

전체 파일은 [`cases/t3-land-permit-2025/plan.yaml`](../../cases/t3-land-permit-2025/plan.yaml)에 있습니다. 아래는 실데이터로 바꾼 뒤의 핵심만 옮긴 것이고, 자동 검사가 이 예시가 스키마를 통과하는지 매번 확인합니다.

```yaml
case_id: t3-land-permit-2025
title: "토지거래허가구역 확대 지정(2025.3.24)이 강남·서초·송파·용산 아파트 거래에 미친 효과"
question: >
  2025년 3월 24일 강남·서초·송파·용산구 전체 아파트를 토지거래허가구역으로 지정한 뒤,
  서울의 나머지 21개 자치구와 비교해 이 4개 구의 아파트 매매 거래건수와 ㎡당 가격이 달라졌는가?
synthetic_data: false                    # 실데이터로 바꾼 모습 (레포의 예시 파일은 지금 시뮬레이션)

unit: {name: 자치구, id_col: gu_code}
time: {col: month_idx, freq: month, start: 0, end: 20}   # 0 = 2024-01

treatment:
  definition: "2025.3.24 전역 지정 자치구. 첫 처치 월 = 2025-04 (month_idx 15)"
  group_col: treated
  treat_time: 15
control:
  definition: "서울 나머지 21개 자치구 (2025.9까지 미지정)"
  rationale: "같은 금리·대출 규제·서울 전체 수요 충격을 받는다. 2025.10.20 전역 지정 이후는 대조군이 없어 뺀다"

outcomes:
  - {name: 아파트 매매 거래건수(로그), col: log_trades, definition: "log(1+월별 매매 건수)", primary: true, expected_direction: decrease}
  - {name: ㎡당 거래가격 중위값(로그), col: log_price_m2, definition: "log(가격÷전용면적의 중위값)", expected_direction: unknown}

estimator: {method: event_study, cluster_col: gu_code, ref_period: -2, window: [-8, 5], alpha: 0.05}

assumptions:
  - {name: 평행추세, description: "지정이 없었다면 두 집단의 추세는 같았을 것", check: pretrend_test}
  - {name: 선반영 없음, description: "2025.2.12 해제 직후 급등 → 가짜 시점 검정", check: placebo_time}

refutations:
  - {kind: placebo_time, params: {shift: 3}}

abstention:
  - {when: pretrend_rejected, verdict: not_identified}
  - {when: placebo_significant, verdict: conditional}
  - {when: ci_crosses_zero, verdict: conditional}

thresholds: {pretrend_alpha: 0.10, min_clusters: 20, min_pre_periods: 3}

data_sources:
  - name: "국토교통부_아파트 매매 실거래가 상세 자료"
    provider: "국토교통부 (공공데이터포털 15126468)"
    url: "https://www.data.go.kr/data/15126468/openapi.do"
    license: KOGL-1
    adapter: molit
```

사이트 대화창의 "분석 계획 초안" 버튼도 같은 모양의 초안을 만들어 줍니다. 초안의 `<내ID>`와 인덱스(`treat_time`, `end`)는 내 데이터에 맞게 고칩니다.

## 3. `make flow`가 plan.yaml로 하는 일

1. ① 계획 확인: 칸 검증, `case_id` = 폴더 이름 확인, **git 커밋 여부 확인**(안 되어 있으면 멈춤)
2. ② 수집: `fetch.py`를 실행해 `data/panel.csv`를 만듭니다
3. ③ 정리: 칸에 적은 열이 있는지, 결측·중복을 점검합니다
4. ④ 계산: `estimator`로 추정하고 `refutations`와 `abstention`을 적용합니다. 정책 받은 곳이 10곳 미만이면 무작위화 추론으로 바꿉니다
5. ⑤ 과장 점검: 근거가 부족하면 "입증", "때문에" 같은 표현을 막습니다
6. ⑥ 리포트: `report.md`를 새로 만들고 `discussion.md`를 끝에 붙입니다. 실행 기록은 `run_manifest.json`에 남습니다
