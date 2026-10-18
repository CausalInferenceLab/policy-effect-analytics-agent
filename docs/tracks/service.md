# 트랙 C. 서비스 개발 — 분석 Cycle의 데이터로 웹·앱 만들기

> 서비스를 개발하고 싶은 분. 서버 없이 공개 API를 읽는 정적 웹 서비스부터 시작합니다.

## 쓸 수 있는 데이터 (공개 API)

사이트를 만들 때 함께 생성되고 매일 갱신됩니다. 주소 앞에 `https://causalinferencelab.github.io/policy-effect-analytics-agent/`를 붙입니다.

| 주소 | 내용 | 만드는 쪽 |
|---|---|---|
| `api/index.json` | 목록 · 생성 시각 · 이용 조건(`terms`) | — |
| `api/topics.json` | 주제 8개: 세 가지 확인 상태, 사건, 근거 법률과 최근 개정 | 운영 |
| `api/issues.json` | 지금 이슈인 정책: 시작일, 비교 대상, 설계, 쓰는 데이터 | 운영 |
| `api/datasets.json` | 데이터 지도: 역할 · 단위 · 받는 법 · 이용 조건 | 트랙 A |
| `api/legal/<주제>.json` | 법제처에서 모은 법령·행정규칙·조례 | 자동 수집 |
| `api/lineage.json` | 데이터 계보 그래프(`nodes`, `edges`, `lineages`) | 트랙 A |
| `api/results.json` | 분석 결과: `verdict`, `outcomes[].estimate`·`ci`·`p_value`, `figures` | 트랙 B |

```js
const API = "https://causalinferencelab.github.io/policy-effect-analytics-agent/api/";
const results = await (await fetch(API + "results.json")).json();
```

## 시작

```bash
git switch -c <내ID>/app
cp -r apps/_template apps/<내ID>-<서비스>        # app.yaml 의 title·owner·description 수정
make site                                          # http://localhost:8000/apps/<내ID>-<서비스>/
```

- 템플릿([`apps/_template`](../../apps/_template/))은 주제를 고르면 이슈·최근 법령·계보·분석 결과를 보여 주는 예시입니다. 사이트에서 바로 열어 볼 수 있습니다.
- PR이 합쳐지면 `/apps/<폴더 이름>/`에서 열리고 [서비스](https://causalinferencelab.github.io/policy-effect-analytics-agent/apps.html) 페이지에 소개됩니다.
- React·Vue·Svelte를 쓰면 빌드 결과를 폴더에 두거나, Vercel·Netlify·Streamlit Cloud 등에 배포하고 `app.yaml`의 `url`에 주소를 적습니다.

## 아이디어

- **정책 알림**: `legal/<주제>.json`과 `issues.json`으로 "내 관심 주제의 법령이 바뀌었어요" 피드
- **지역 비교 지도**: `results.json`의 그림·추정치를 주제별 카드나 지도로
- **데이터 계보 탐색기**: `lineage.json`을 그래프로 그려 이슈에서 지표까지 클릭으로 따라가기
- **분석 계획 도우미**: `topics.json`·`datasets.json`으로 질문을 넣으면 쓸 데이터와 세 가지 확인 상태를 보여 주기

## 규칙

- API 키·비밀값을 넣지 않습니다. 정적 파일은 누구나 볼 수 있습니다.
- 화면에 "공식 평가가 아님"과 출처를 보여 줍니다(`index.json`의 `terms`). 네이버 검색량 같은 제3자 원시값은 다시 배포하지 않습니다.
- 결과를 다시 계산하거나 판정을 바꿔 보여 주지 않습니다. 판정은 트랙 B의 분석이 냅니다.
