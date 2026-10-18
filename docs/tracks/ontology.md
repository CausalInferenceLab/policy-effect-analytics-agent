# 트랙 A. 데이터 온톨로지 — 공공 이슈와 데이터를 잇는 계보(Lineage)

> 데이터 온톨로지를 만들고 싶은 분. "이 숫자는 어디서 와서 어떻게 만들어졌나"를 누구나 따라갈 수 있게 만듭니다.

## 무엇을 만드나

한 파일(`catalog/lineage/<내ID>-<주제>.yaml`)이 한 개의 길을 적습니다.

```
이슈 ──▶ 정책(법령·공고·발표) ──▶ 원천 데이터 ──▶ 가공 ──▶ 지표 ──▶ 분석(cases/)
issue     policy                   dataset          transform  metric   used_by
```

| 단계 | 적는 것 | 확인하는 것 |
|---|---|---|
| `issue` | `ref`: `catalog/issues.yaml`의 id | 있는 이슈인지 |
| `policy` | `ref`: 법령·행정규칙 이름(주제 페이지의 관련 법령) 또는 `source`: 발표문 URL, `date` | 법제처 스냅샷에 있거나 출처가 있는지 |
| `dataset` | `ref`: `catalog/datasets.yaml`의 id, 새 데이터면 `url` | 카탈로그에 있는지 (없으면 추가 권장) |
| `transform` | `inputs`, `how`(무엇을 걸렀고 묶었나), `keys`(결합 키) | 입력이 앞 단계에 있는지 |
| `metric` | `inputs`, `how`(계산식), `used_by`(쓰는 케이스) | 케이스 폴더가 있는지 |

모든 단계에 함께 쓸 수 있는 것:

| 필드 | 뜻 | 확인하는 것 |
|---|---|---|
| `status` | `done`(기본) · `planned`(하려는 단계) · `missing`(필요하지만 아직 없는 데이터 = **빈칸**) | `missing`은 `dataset`에만, ref·url 없이 적을 수 있음 |
| `artifact` | 이 단계를 만든 결과물 파일 (예: 역 → 시군 매핑표 CSV). `catalog/lineage/data/`에 둡니다 | 파일이 레포에 있는지 |

빈칸(`missing`)은 사이트의 [데이터 계보](https://causalinferencelab.github.io/policy-effect-analytics-agent/lineage.html) "주제별 연결 상태"에 개수로 나옵니다. 빈칸을 찾아 채우는 것이 트랙 A의 가장 좋은 기여입니다.

예시:
- [`catalog/lineage/t3-land-permit-2025.yaml`](../../catalog/lineage/t3-land-permit-2025.yaml) — 토허구역 지정 → 실거래가 → 자치구×월 집계 → 거래량 지표 → 분석
- [`catalog/lineage/climate-card-expansion.yaml`](../../catalog/lineage/climate-card-expansion.yaml) — 기후동행카드 편입 6회 + 교란 사건 3개 → 역×일 승하차 → 역 처치표(`artifact`) → 역×주 평일 패널 → 평일 승차 지표 → [성남 케이스](../../cases/t3-climate-card-seongnam/). 빈칸 2개(권종별 자료, 김포골드라인 역 자료), 계획 3개(시간대 패널·지표)

## 순서

```bash
git switch -c <내ID>/lineage
cp catalog/lineage/_template.yaml catalog/lineage/<내ID>-<주제>.yaml   # id 도 같은 이름으로
make lineage                                                          # 참조 검사
make site                                                             # http://localhost:8000/lineage.html
```

1. **이슈 고르기**: [지금 이슈](https://causalinferencelab.github.io/policy-effect-analytics-agent/issues.html)나 사이트 질문(`from-site` 이슈)에서 고릅니다. [데이터 계보](https://causalinferencelab.github.io/policy-effect-analytics-agent/lineage.html)의 "주제별 연결 상태"에서 빈칸이 있는 주제가 기여 효과가 큽니다.
2. **정책 근거 찾기**: 주제 페이지의 "관련 법령·행정규칙"(법제처 자동 수집)에서 시작 근거를 찾습니다. 지자체 공고·행정지도처럼 법령 DB에 없는 것은 발표문 URL을 `source`로 적습니다.
3. **데이터 찾기**: [데이터 지도](https://causalinferencelab.github.io/policy-effect-analytics-agent/data.html)에서 처치(누가 언제)·결과(무엇이 변했나)·통제(다른 요인) 데이터를 고릅니다. 없으면 공공데이터포털·KOSIS에서 찾아 `datasets.yaml`에 추가합니다(역할·단위·받는 법·이용 조건·확인 날짜).
4. **가공과 지표 적기**: 원자료를 분석 단위로 바꾸는 과정(코드 매핑, 제외 조건, 집계)을 `how`에, 다른 데이터와 붙이는 키를 `keys`에 적습니다. 행정구역 코드 변경처럼 함정이 있으면 `note`에 남깁니다.
5. **검사하고 PR**: `make lineage`가 통과하면 PR을 올립니다.

## 좋은 계보의 기준

- 처음 보는 사람이 원천 데이터 페이지에서 지표 숫자까지 같은 방법으로 다시 만들 수 있다.
- 정책 시작일에 출처가 있다. 법령 개정일을 그대로 처치 시점으로 쓰지 않는다.
- 이용 조건이 다른 데이터(공공누리 유형, KOSIS 약관)를 섞을 때 무엇을 다시 배포할 수 없는지 적는다.
- 트랙 B 분석과 `used_by`로 이어진다 (같은 주제를 고른 B 멘티와 함께 하면 가장 좋습니다).

## 함께 쓰면 좋은 것

- `scripts/refresh_legal.py` · `catalog/snapshots/legal_*.csv`: 법제처 법령·행정규칙·조례 목록
- [korean-law-mcp](https://github.com/chrisryugj/korean-law-mcp): Claude 같은 AI로 법령을 탐색할 때
- 사이트 대화창: 주제에 맞는 데이터와 관련 법령을 대화로 찾기
