# 서비스 템플릿 (트랙 C)

공개 API만 읽어 화면을 만드는 정적 웹 서비스의 출발점입니다. 서버가 필요 없고, PR이 합쳐지면
`https://causalinferencelab.github.io/policy-effect-analytics-agent/apps/<폴더 이름>/` 에서 바로 열립니다.

```bash
git switch -c <내ID>/app
cp -r apps/_template apps/<내ID>-<서비스>      # 예: apps/gildong-policy-alarm
# app.yaml 의 title·owner·description 수정 → index.html·app.js 고치기
make site                                        # http://localhost:8000/apps/<내ID>-<서비스>/ 에서 확인
```

## 쓸 수 있는 데이터 (공개 API)

| 주소 | 내용 |
|---|---|
| `api/index.json` | 목록 · 생성 시각 · 이용 조건 |
| `api/topics.json` | 주제 8개 (세 가지 확인 상태, 사건, 근거 법률과 최근 개정) |
| `api/issues.json` | 지금 이슈인 정책 (시작일, 비교 대상, 설계, 쓰는 데이터) |
| `api/datasets.json` | 데이터 지도 (역할 · 단위 · 받는 법 · 이용 조건) |
| `api/legal/<주제>.json` | 법제처에서 모은 법령·행정규칙·조례 목록 |
| `api/lineage.json` | 데이터 계보 그래프 (트랙 A 산출물) |
| `api/results.json` | 분석 결과: 판정 · 추정치 · 신뢰구간 · 그림 (트랙 B 산출물) |

전체 설명: [docs/tracks/service.md](../../docs/tracks/service.md)

## 규칙

- 이 폴더에는 정적 파일(html · css · js · json · 이미지)만 둡니다. API 키를 넣지 않습니다(누구나 볼 수 있음).
- React·Vue 같은 빌드 도구를 쓰면 빌드 결과(dist)를 이 폴더에 두거나, 다른 곳에 배포하고 `app.yaml`의 `url`에 주소를 적습니다.
- 화면에 "공식 평가가 아님"과 데이터 출처를 보여 줍니다(`index.json`의 `terms`).
