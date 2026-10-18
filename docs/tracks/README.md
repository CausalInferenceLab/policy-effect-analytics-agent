# 세 가지 참여 방식 (트랙)

커리어 방향과 해 보고 싶은 시도에 따라 하나를 고릅니다. 중간에 바꿔도 되고, 둘을 함께 해도 됩니다.

| 트랙 | 이런 분께 | 하는 일 | 내 작업 공간 | 결과가 보이는 곳 |
|---|---|---|---|---|
| **A. 데이터 온톨로지** | 데이터 온톨로지를 만들고 싶다 | 공공 이슈와 연결되는 데이터를 찾고 계보(Lineage)를 만든다 | `catalog/lineage/<내ID>-<주제>.yaml`, `catalog/datasets.yaml` | [데이터 계보](https://causalinferencelab.github.io/policy-effect-analytics-agent/lineage.html), `api/lineage.json` |
| **B. 가설과 분석** | 가설 설정과 분석을 익히고 싶다 | 실제 사례로 효과를 추정하는 Cycle을 한 바퀴 돈다 | `cases/<내ID>-<주제>/` | 주제 페이지의 분석 예시, `api/results.json` |
| **C. 서비스 개발** | 서비스를 개발하고 싶다 | 분석 Cycle에서 나온 데이터로 웹·앱 서비스를 만든다 | `apps/<내ID>-<서비스>/` | [서비스](https://causalinferencelab.github.io/policy-effect-analytics-agent/apps.html), `/apps/<이름>/` |

## 세 트랙은 이어져 있습니다

```
 A. 데이터 온톨로지            B. 가설과 분석               C. 서비스 개발
 이슈 → 정책 → 데이터 → 지표  ─▶  가설 → 계획 → 추정 → 판정  ─▶  공개 API로 화면 만들기
 catalog/lineage/*.yaml          cases/*/                       apps/*/
        └──────────── api/lineage.json ──── api/results.json ────────┘
```

- A가 만든 계보의 `metric`(지표)은 B의 `plan.yaml` 결과 지표가 되고, `used_by`로 서로 연결됩니다.
- B가 `make flow`로 낸 판정·추정치·그림은 매일 `api/results.json`으로 공개되어 C의 재료가 됩니다.
- C의 서비스가 보여 주는 빈칸(예: 결과가 없는 주제)은 다시 A·B의 다음 작업이 됩니다.

## 남은 2주 목표

| 모임 | A. 데이터 온톨로지 | B. 가설과 분석 | C. 서비스 개발 |
|---|---|---|---|
| 10.25(일) | 이슈 하나의 계보 YAML PR (`make lineage` 통과) | `plan.yaml` PR + `fetch.py`로 `data/panel.csv` | `apps/<내ID>-<서비스>/` 첫 화면 PR (API 하나 이상 사용) |
| 11.1(일) 공개 | 새 데이터셋 1개 이상 `datasets.yaml`에 추가, 계보가 사이트에 표시 | `make flow` 결과 + `discussion.md`, 다른 멘티가 재현 | 기능 1개 완성 + README, 사이트에서 열림 |

어느 트랙이든 **작업 제안 이슈**를 먼저 열고(트랙 선택), 같은 주제를 고른 사람끼리는 이슈에서 서로를 연결합니다.

트랙별 가이드: [A. 데이터 온톨로지](ontology.md) · [B. 가설과 분석](analysis.md) · [C. 서비스 개발](service.md)
