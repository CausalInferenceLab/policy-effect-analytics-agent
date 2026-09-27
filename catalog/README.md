# catalog/ — 데이터 지도

정책 효과를 재는 데 필요한 것을 네 개의 파일로 정리합니다. 사이트의 [데이터 지도](https://causalinferencelab.github.io/policy-effect-analytics-agent/data.html)와 [지금 이슈](https://causalinferencelab.github.io/policy-effect-analytics-agent/issues.html)는 이 파일들에서 자동으로 만들어집니다.

```
                ┌── 근거 ──▶ 법령·행정규칙·조례 (snapshots/legal_<주제>.csv, 법제처 자동 수집)
                │             연혁(개정일) · 체계도(하위 규정) · 지정/해제 공고 이력
주제 (topics.yaml) ── 속한다 ◀── 이슈 (issues.yaml, 지금 논쟁 중인 정책)
   │                                 │
   └──────── 쓴다 ────────▶ 데이터셋 (datasets.yaml) ── 제공 ──▶ 포털
                               역할 · 단위 · 받는 법 · 이용 조건
```

## 법령·정책 온톨로지 (법제처 자동 수집)

주제마다 `topics.yaml`의 `legal`에 **출발점만** 적습니다. 나머지는 수집기가 따라가 모읍니다.

```yaml
legal:
  laws: [부동산 거래신고 등에 관한 법률, 주택법]      # 근거 법률의 정확한 이름
  admin_rules: [투기과열지구, 조정대상지역]           # 행정규칙 이름의 앞부분
  note: "API에 없는 것(지자체 공고, 행정지도)과 대신 볼 곳"
```

| 따라가는 길 | 모이는 것 | 예 (부동산 거래 규제) |
|---|---|---|
| 연혁 | 근거 법률과 시행령·시행규칙의 모든 개정 (공포일·시행일) | 법령 개정 1,146건 |
| 체계도 | 하위 행정규칙(고시·공고·훈령)과 자치법규(조례·규칙) | 행정규칙 92건 · 자치법규 576건 |
| 이력 | 지정·해제 공고의 모든 판 | 투기과열지구 지정 2025.10.16 · 2026.7.1, 지정 해제 2023.1.5 |
| 변경 감지 | 지난 7일 사이 바뀐 것 → 매주 월요일 `law-change` 이슈 | 주택법 일부개정 2026.9.8 |

- 실행: `LAW_OC=... python scripts/refresh_legal.py` (Actions에서는 레포 Secrets의 `LAW_OC`로 매일), `python scripts/watch_legal.py --days 7`
- 저장하는 것은 이름·날짜·종류 같은 메타데이터와 OC 없는 공개 링크뿐입니다. 출처: 법제처 국가법령정보센터.
- **법령 개정이 곧 처치 시점은 아닙니다.** 시행일·대상을 공식 발표로 확인한 뒤 사람이 `events`에 옮깁니다.
- API에 없는 것: 지자체 고시·공고(예: 서울시 토지거래허가구역 지정), 금융당국 행정지도(예: 대출 한도). 이런 사건은 `events`에 출처와 함께 적습니다.

| 파일 | 무엇 | 언제 고치나 |
|---|---|---|
| `topics.yaml` | 주제 8개. 키워드, 정책 시점, 세 가지 확인(언제·누가·무엇으로) | 새 주제를 제안할 때 |
| `issues.yaml` | 지금 이슈인 정책 6개. 시작일(공식 출처), 비교 방법, 쓸 데이터, 조심할 점 | 새 이슈를 분석하고 싶을 때 |
| `datasets.yaml` | 공공데이터 35개. 역할·단위·받는 법·이용 조건·확인 날짜 | 쓸 만한 데이터를 찾았을 때 |
| `policies.yaml` | 분석 예시가 있는 정책의 설계 정보 | 멘티가 분석 케이스를 만들 때 |
| `snapshots/` | 법제처에서 자동으로 모은 법령·조례 목록 (직접 고치지 않음) | 수집기가 갱신 |

## 데이터셋의 세 가지 역할

| 역할 | 질문 | 예시 |
|---|---|---|
| 처치 `treatment` | 누가, 언제 정책을 받았나 | 법제처 조례 목록, 지역사랑상품권 판매정책 |
| 결과 `outcome` | 무엇이 달라졌나 | 아파트 실거래가, 교통사고 통계, 출생등록자 수 |
| 통제 `covariate` | 결과에 영향을 준 다른 요인 | 기상 관측, 주민등록 인구 |

세 역할이 모두 있어야 분석을 시작할 수 있습니다.

## 데이터셋 추가하기

`datasets.yaml`에 아래처럼 한 항목을 넣고 PR을 올리세요. **원본 페이지를 열어 확인한 값만** 적고, 모르면 `확인필요`라고 씁니다.

```yaml
- id: "15126468"                     # 포털의 데이터 ID
  name: 국토교통부_아파트 매매 실거래가 상세 자료
  provider: 국토교통부
  portal: data.go.kr                 # data.go.kr | kosis | seoul | law | ...
  url: https://www.data.go.kr/data/15126468/openapi.do
  access: open_api                   # open_api | file | manual
  approval: 자동승인                  # 자동승인 | 즉시 | 심의 | 없음 | 확인필요
  license: other                     # KOGL-1~4 | other | 확인필요
  space: 시군구                       # 전국 | 시도 | 시군구 | 읍면동 | 지점 | 개별
  time: 월                           # 일 | 주 | 월 | 분기 | 연 | 수시
  measures: [거래금액, 전용면적, 계약일]
  roles: [outcome]
  topics: [housing-regulation]
  verified: "2026-09-27 페이지 확인"
```

`python -c "from core.discovery.ontology import check_links; print(check_links())"`가 빈 목록이면 연결이 맞습니다(CI에서도 확인합니다).
