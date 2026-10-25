# 성과 측정

사이트가 목표대로 쓰이는지 [성과 화면](https://causalinferencelab.github.io/policy-effect-analytics-agent/impact.html)이 매일 다시 셉니다. 같은 숫자는 [`api/metrics.json`](https://causalinferencelab.github.io/policy-effect-analytics-agent/api/metrics.json)으로도 받을 수 있습니다. 목표는 [roadmap.md](roadmap.md)에서 정합니다.

## 무엇을 세나

| 묶음 | 지표 | 어디서 | 목표 |
|---|---|---|---|
| 쓰임 | 방문(페이지뷰), 분석 결과 화면 조회 | GoatCounter (선택) | 기록 |
| 쓰임 | 결과를 가져간 횟수 = 인용문 복사 + 링크 복사 + CSV 내려받기 | GoatCounter 이벤트 | 기록 |
| 쓰임 | 대화창 질문, 제안으로 올라온 질문 | GoatCounter 이벤트, `from-site` 이슈 | 기록 |
| 외부 검증 | 사용자 과업 테스트 수 | `user-test` 이슈 ([user-test.md](user-test.md)) | 5명 |
| 외부 검증 | 혼자 찾아 바르게 인용 (과업 1 '혼자 찾음' + 과업 2 '바르게 말함') | 같은 이슈의 응답 | 4/5 — 1단계 관문 |
| 결과의 질 | 한 문장 해석 · 교차 재현 · 계획 먼저 커밋 | `discussion.md`, `catalog/projects.yaml`, git 기록 | 결과 전부 |
| 참여 | 참여자, 머지된 참여자 PR, 리뷰를 받고 머지된 비율, 작업 제안, 스타·포크 | GitHub API | 리뷰: 전부 |

측정하지 못한 칸은 0이 아니라 **측정 전**으로 둡니다. 0과 "안 셌다"를 섞으면 성과를 잘못 읽기 때문입니다.

## 버튼 이벤트

사이트 버튼에 `data-track="이름"`을 붙이면 셉니다. 이름 목록은 `site/impact.py`의 `EVENTS`이고, 테스트(`test_impact_page_and_tracking`)가 사이트에 쓰인 이름이 목록에 있는지 확인합니다.

| 이름 | 버튼 |
|---|---|
| `cite-copy` | 답 페이지 '인용문 복사' |
| `link-copy` | 답 페이지 '링크 복사' |
| `csv-download` | 케이스 CSV · 전체 결과 CSV |
| `ask` | 대화창에 질문 보내기 |
| `propose` | 대화를 '제안으로 올리기' |
| `search` | 분석 결과 검색 (페이지당 한 번) |
| `reproduce` | 답 페이지 '재현 기록 남기기' |

## 방문 통계 켜기 (메인테이너, 한 번)

쿠키를 쓰지 않는 [GoatCounter](https://www.goatcounter.com)를 씁니다. 개인 식별 정보를 저장하지 않고, 브라우저의 '추적 안 함' 설정을 따릅니다. 꺼져 있으면 사이트는 통계 스크립트를 아예 불러오지 않습니다.

1. goatcounter.com에서 사이트를 만들고 코드(예: `policy-effect`)를 정합니다. 계정은 메인테이너가 직접 만듭니다.
2. 레포 **Settings → Secrets and variables → Actions → Variables**에 `GOATCOUNTER_CODE` = 코드. 다음 배포부터 통계가 켜지고, 사이트 하단에 이용 통계 안내가 붙습니다.
3. (성과 화면에 숫자 표시) GoatCounter **Settings → API**에서 읽기 권한 토큰을 만들어 **Secrets**에 `GOATCOUNTER_TOKEN`으로 넣습니다. 매일 배포 때 최근 30일 수치를 받아 성과 화면에 그립니다.

토큰 값은 레포·이슈·PR 어디에도 적지 않습니다.

## 로컬에서 보기

```bash
GITHUB_TOKEN=$(gh auth token) GITHUB_REPOSITORY=CausalInferenceLab/policy-effect-analytics-agent \
  python scripts/refresh_metrics.py      # data/cache/metrics.json (git 에 올라가지 않음)
python site/build.py                     # _site/impact.html
```
