# 트랙 B. 가설과 분석 — 실제 사례로 효과를 추정하는 Cycle

> 가설 설정과 분석을 익히고 싶은 분. 한 사례로 가설 → 계획 → 수집 → 추정 → 반증 → 해석을 한 바퀴 돕니다.

## 한 바퀴(Cycle)

| 단계 | 할 일 | 파일 | 확인 |
|---|---|---|---|
| 1. 가설 | "이 정책이 누구의 무엇을 어느 방향으로 바꿨나" 한 문장 + 예상 방향 | `plan.yaml`의 `question`, `outcomes[].expected_direction` | 대조군이 있는 질문인가 |
| 2. 계획 | 처치·대조·시점·지표·방법·판정 낮출 조건 | `plan.yaml` | **데이터를 보기 전에 커밋** |
| 3. 수집 | 공공데이터 → 분석 단위 표 | `fetch.py` → `data/panel.csv` | ③ 품질 점검 통과 |
| 4. 추정 | 규칙이 고른 방법으로 계산 | `make flow` | 사전 추세, 정책 지역 수 |
| 5. 반증 | 가짜 시작일 · 가짜 지표 · 단위 빼기 | `plan.yaml`의 `refutations` | 가짜에서도 효과가 나오지 않는가 |
| 6. 해석 | 판정(효과 근거 있음 · 크기를 판별하지 못함 · 판단 불가)과 한계 | `discussion.md` | 과장 표현 점검 통과 |

판정·추정치·그림은 사이트 주제 페이지와 `api/results.json`에 자동으로 공개되어 트랙 C의 재료가 됩니다.

## 시작

```bash
git switch -c <내ID>/plan
cp -r cases/_template cases/<내ID>-<주제>        # case_id 를 폴더 이름과 같게
make demo                                         # 예시로 한 바퀴 먼저 돌려 보기
```

- 계획 쓰는 법: [plan-guide.md](../strategy/plan-guide.md) (검증을 통과하는 예시 포함)
- 사이트 대화창의 "분석 계획 초안" 버튼으로 출발점을 만들 수 있습니다.
- 같은 주제의 트랙 A 계보가 있으면 그 `metric`을 결과 지표로 쓰고, 계보의 `used_by`에 내 케이스를 적어 연결합니다.

## 데이터 모양에 따른 방법

| 데이터 모양 | 방법 | 지금 |
|---|---|---|
| 여러 지역이 같은 날 시작 | 이중차분 · 이벤트 스터디 | 사용 가능 |
| 정책 지역이 10곳 미만 | 위와 같되 무작위화 추론으로 자동 전환 | 사용 가능 |
| 대조 지역 없이 한 곳의 시계열 | 단절 시계열 | 사용 가능 |
| 하루 중 특정 시간대에만 적용 (측정소 × 시간) | 이벤트 스터디 + `event_bin`(일·주 묶음) + `placebo_window`(적용 외 시간대 반증) | 사용 가능 — [plan-guide](../strategy/plan-guide.md#시간-단위-자료-예-측정소--시간) |
| 지역마다 시작일이 다름 | 시차 도입 이중차분 | 준비 중 — 그 전까지는 같은 날 시작한 지역만 골라 1차 추정 |
| 정책 지역이 1~5곳 | 합성통제 | 준비 중 — 그 전까지는 무작위화 추론으로 1차 추정, 한계에 기록 |

## 비교군을 못 찾았을 때: 관측 통계로 공개하기

정책 지역과 비교할 곳을 끝내 고르지 못했거나 시작일이 확인되지 않으면 `make flow` 대신 **관측 통계**로 공개할 수 있습니다.
사이트에는 `관측 통계 · 정책 효과 미추정` 배지가 붙고, 효과·신뢰구간·p값 없이 연도별 관측값·지표 정의·출처·재생 명령만 보입니다.
예시: [`cases/inshining-elderly-driver`](../../cases/inshining-elderly-driver) (@inshining, 부산 고령운전자 면허반납).

`flow_log.json`에 아래 모양을 직접 씁니다. 사이트 빌드(`site/answers.py`의 `normalize_descriptive`)가 하나라도 어긋나면 그 케이스를 건너뛰고 이유를 출력합니다.

```json
{
  "execution_kind": "descriptive_only",
  "causal_estimation": "not_run",
  "verdict": "not_identified",
  "results": [],
  "generated_at": "2026-11-01T00:00:00+00:00",
  "descriptive": {
    "columns": [{"key": "year", "label": "연도", "unit": "년"}, {"key": "returns", "label": "면허 반납", "unit": "건"}],
    "rows": [{"year": 2019, "returns": 12345}],
    "definitions": {"returns": "그 해 자진반납한 65세 이상 운전면허 수"},
    "sources": [{"name": "자료 이름", "provider": "기관", "url": "https://...", "license": "open"}],
    "reproduction": {"command": "python3 cases/<케이스>/run.py", "mode": "offline replay", "prerequisites": ["원자료 확보 방법"]}
  }
}
```

- 열 이름에 `estimate`·`effect`·`ci`·`p_value` 같은 효과 필드는 쓸 수 없습니다. `year` 열(단위 `년`)은 반드시 있어야 합니다.
- 관측 통계는 끝이 아니라 중간 결과입니다. `discussion.md`에 "어떤 비교군·자료가 있으면 효과를 추정할 수 있는지"를 적어 두면 다음 사람이 이어받습니다.

## 완주 기준

- 다른 참여자가 README만 보고 `fetch.py` → `make flow`로 같은 결과를 낸다.
- "판단 불가"도 좋은 결과다. 무엇 때문에 판단할 수 없고 어떤 데이터가 있으면 판단할 수 있는지 적는다.
