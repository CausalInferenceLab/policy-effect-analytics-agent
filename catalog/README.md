# catalog/ — 데이터 지도

정책 효과를 재는 데 필요한 것을 네 개의 파일로 정리합니다. 사이트의 [데이터 지도](https://causalinferencelab.github.io/policy-effect-analytics-agent/data.html)와 [지금 이슈](https://causalinferencelab.github.io/policy-effect-analytics-agent/issues.html)는 이 파일들에서 자동으로 만들어집니다.

```
주제 (topics.yaml) ── 속한다 ◀── 이슈 (issues.yaml, 지금 논쟁 중인 정책)
   │                                 │
   └──────── 쓴다 ────────▶ 데이터셋 (datasets.yaml) ── 제공 ──▶ 포털
                               역할 · 단위 · 받는 법 · 이용 조건
```

| 파일 | 무엇 | 언제 고치나 |
|---|---|---|
| `topics.yaml` | 주제 8개. 키워드, 정책 시점, 세 가지 확인(언제·누가·무엇으로) | 새 주제를 제안할 때 |
| `issues.yaml` | 지금 이슈인 정책 6개. 시작일(공식 출처), 비교 방법, 쓸 데이터, 조심할 점 | 새 이슈를 분석하고 싶을 때 |
| `datasets.yaml` | 공공데이터 35개. 역할·단위·받는 법·이용 조건·확인 날짜 | 쓸 만한 데이터를 찾았을 때 |
| `policies.yaml` | 분석 예시가 있는 정책의 설계 정보 | 멘티가 분석 케이스를 만들 때 |

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
