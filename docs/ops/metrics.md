# 사이트 지표

사이트가 목표대로 쓰이는지 [성과 화면](https://causalinferencelab.github.io/policy-effect-analytics-agent/impact.html)이 매일 다시 셉니다. 같은 숫자는 [`api/metrics.json`](https://causalinferencelab.github.io/policy-effect-analytics-agent/api/metrics.json)으로 받을 수 있습니다. 목표와 계획은 [roadmap.md](roadmap.md)에 있습니다.

측정하지 못한 칸은 0이 아니라 **측정 전**으로 둡니다. 0과 "안 셌다"를 섞으면 성과를 잘못 읽기 때문입니다.

## 지표 나무

```
북극성 ─ 주간 가져간 답 (인용문 복사 + 링크 복사 + CSV 내려받기, 7일 환산)
  │
  ├─ 수요(입력) ── 도달 → 이해 → 가져감 → 참여
  │    도달   방문 · 이슈 보드 조회
  │    이해   결과 화면 조회 · 흐름 띠 단계 누름 · 결과 검색
  │    가져감 (북극성)
  │    참여   대화창 질문 → 제안으로 올린 질문 → 작업 제안 → 결과
  │
  ├─ 공급(입력) ── 이슈 보드가 얼마나 채워졌나
  │    다섯 단계(이슈·공공데이터·계보·분석·대시보드)를 모두 채운 보드
  │    지금 이슈 주제 중 대시보드까지 있는 것
  │    오늘 바로 받을 수 있는 데이터 · 계보로 이어진 데이터
  │    법령 목록 경과일
  │
  └─ 지켜야 할 선(신뢰)
       외부 과업 테스트에서 판정을 넘지 않게 인용한 비율
       교차 재현 · 리뷰를 받고 머지된 PR · 계획 먼저 커밋 · 한 문장 해석
```

**왜 방문 수가 아니라 '가져간 답'인가.** 이 사이트의 목적은 공공데이터로 확인한 답이 판정을 넘지 않는 형태로 기사·보고서·회의에서 쓰이는 것입니다. 방문은 많아도 답을 가져가지 않으면 목적을 이루지 못한 것이고, 반대로 방문이 적어도 실무자가 인용문을 가져가면 이룬 것입니다. 다만 가져간 뒤 잘못 인용하면 해가 되므로 **외부 과업 테스트의 바른 인용 비율**을 같이 봅니다(지켜야 할 선).

## 정의

| 묶음 | 지표 | 계산 | 출처 | 목표 |
|---|---|---|---|---|
| 북극성 | 주간 가져간 답 | (`cite-copy` + `link-copy` + `csv-download`) × 7 / 집계 일수 | GoatCounter 이벤트 | 기록 후 기준선 설정 |
| 도달 | 방문 | 페이지뷰 | GoatCounter | 기록 |
| 도달 | 이슈 보드 조회 | `/topics/` 페이지뷰 | GoatCounter | 기록 |
| 이해 | 결과 화면 조회 | `/results` + `/answers/` 페이지뷰 | GoatCounter | 기록 |
| 이해 | 흐름 띠 단계 누름, 결과 검색 | `flow-stage`, `search` 이벤트 | GoatCounter | 기록 |
| 참여 | 대화창 질문 → 제안 | `ask` → `propose` 이벤트, `from-site` 이슈 | GoatCounter, GitHub | 전환율 기록 |
| 참여 | 작업 제안, 참여자, 머지된 참여자 PR | `[작업]` 이슈, PR 작성자 | GitHub | 기록 |
| 공급 | 완성된 이슈 보드 | 다섯 단계 모두 1 이상인 주제 수 / 주제 수 | 레포 파일 | 지금 이슈 주제 전부 |
| 공급 | 지금 이슈 중 대시보드까지 | 지금 이슈가 있는 주제 중 시점별 계수가 있는 결과가 있는 것 | 레포 파일 | 전부 |
| 공급 | 오늘 받을 수 있는 데이터 | 승인 '없음·즉시·자동승인' / 전체 | `catalog/datasets.yaml` | 기록 |
| 공급 | 계보로 이어진 데이터 | 계보 YAML 에서 쓰는 데이터셋 / 전체 | `catalog/lineage/` | 지금 이슈 데이터 전부 |
| 공급 | 법령 목록 경과일 | 오늘 − 마지막 법제처 수집일 | `catalog/snapshots/` | 14일 이하 |
| 선 | 혼자 찾아 바르게 인용 | 과업 1 '혼자 찾음' & 과업 2 '바르게 말함' / 테스트 수 | `user-test` 이슈 | 4/5 이상 |
| 선 | 리뷰를 받고 머지된 참여자 PR | 작성자 아닌 리뷰 ≥1 / 머지된 참여자 PR | GitHub | 전부 |
| 선 | 교차 재현, 계획 먼저 커밋, 한 문장 해석 | 결과 수 대비 | 레포 파일·git 기록 | 결과 전부 |

## 버튼 이벤트

사이트 버튼에 `data-track="이름"`을 붙이면 셉니다. 이름 목록은 `site/impact.py`의 `EVENTS`이고, 테스트가 사이트에 쓰인 이름이 목록에 있는지 확인합니다.

| 이름 | 버튼 |
|---|---|
| `cite-copy` | 답 페이지 '인용문 복사' |
| `link-copy` | 답 페이지 '링크 복사' |
| `csv-download` | 케이스 CSV · 전체 결과 CSV |
| `ask` | 대화창에 질문 보내기 |
| `propose` | 대화를 '제안으로 올리기' |
| `search` | 분석 결과 검색 (페이지당 한 번) |
| `reproduce` | 답 페이지 '재현 기록 남기기' |
| `flow-stage` | 홈 흐름 띠의 단계 누름 |

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
