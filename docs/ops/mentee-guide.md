# 멘티 참여 가이드

이 프로젝트는 **한 사람이 주제 하나**를 맡아 진행합니다. 각자 공용 저장소의 `cases/<내 GitHub ID>-<주제>/` 폴더에 분석을 쌓고, 합쳐지면 [사이트](https://causalinferencelab.github.io/policy-effect-analytics-agent/)에 자동으로 올라갑니다.

## 먼저 볼 것

- [사이트 첫 화면](https://causalinferencelab.github.io/policy-effect-analytics-agent/): 궁금한 정책을 적으면 주제·데이터·분석 방법을 함께 정리해 주는 대화창이 있습니다.
- [지금 이슈](https://causalinferencelab.github.io/policy-effect-analytics-agent/issues.html): 논쟁 중인 정책 6개의 분석 가이드 (비교 방법, 받을 수 있는 데이터, 조심할 점)
- [데이터 지도](https://causalinferencelab.github.io/policy-effect-analytics-agent/data.html): 공공데이터 35개를 역할·단위·받는 법으로 정리
- 분석 예시: [`cases/t3-land-permit-2025/`](../../cases/t3-land-permit-2025/) (토지거래허가구역, 지금은 시뮬레이션 데이터)
- 계획 쓰는 법: [`docs/strategy/plan-guide.md`](../strategy/plan-guide.md)

## 혼자서 끝까지 가는 6단계

| 단계 | 할 일 | 결과물 |
|---|---|---|
| 1. 찾기 | 사이트 대화창이나 지금 이슈에서 주제를 고릅니다 | GitHub 이슈 "케이스 제안" |
| 2. 모으기 | 그 주제의 정책을 모두 모읍니다. 어느 지역이 언제 시작했는지 | 정책 목록 표 |
| 3. 거르기 | 언제 시작했나 · 누가 받았나 · 무엇으로 재나를 확인합니다 | 이슈에 확인 결과 기록 |
| 4. 계획하기 | 데이터를 보기 전에 `plan.yaml`을 쓰고 PR로 올립니다 | 계획 PR |
| 5. 비교하기 | `fetch.py`로 데이터를 받고 `make flow`로 실행합니다 | 수집·분석 PR |
| 6. 말하기 | 판정(효과 근거 있음 · 조건부 · 판단 불가)과 조심할 점을 리포트에 씁니다 | `report.md` |

"판단 불가"도 좋은 결과입니다. 왜 판단할 수 없는지가 분명하면 됩니다.

## 주차별 목표

| 모임 | 주차 | 끝낼 것 |
|---|---|---|
| 9.27(일) | 2주 | 주제 후보 2개 고르기, 데이터 키 신청(공공데이터포털 자동승인) |
| 10.2(금) 오프라인 | — | 주제 1개 확정, `plan.yaml` 계획 PR |
| 10.4(일) | 3주 | `fetch.py`로 데이터 받기, 품질 점검 통과 |
| 10.11(일) | 4주 | 1차 추정과 추세 그림 |
| 10.18(일) | 5주 | 점검 추가, `make flow`로 6단계 한 번에 실행 |
| 10.25(일) | 6주 | 과장 표현 점검 통과, 판정 문구 확정 |
| 11.1(일) | 7주 | 다른 멘티가 README만 보고 다시 돌려 보기 → 공개 |

## 폴더와 브랜치

```bash
git switch -c <내ID>/plan                           # 브랜치: <내 GitHub ID>/<작업>
cp -r cases/_template cases/<내ID>-<주제>           # 예: cases/gildong-local-currency
```

- 수정은 **내 폴더만** 합니다. `core/`를 고쳐야 하면 먼저 이슈를 엽니다.
- PR 하나에 한 단계만 담고, 멘토 또는 다른 멘티 1명 승인 + 자동 검사 통과 뒤 합칩니다.
- 올리면 안 되는 것: API 키(`.env`), 원자료와 가공 데이터 파일, 개인정보. 데이터는 `fetch.py`로 각자 받게 합니다.

## 활동 인증

- 매 모임 전까지 내 브랜치에 커밋 1회 이상, PR 링크를 디스코드에 공유합니다.
- 멘토는 `python scripts/weekly_activity.py`로 케이스 폴더별 커밋을 확인합니다.

GitHub가 처음이라면 [github-onboarding.md](github-onboarding.md)를 따라 하세요.
