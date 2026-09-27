# 멘티 참여 가이드

이 프로젝트는 **한 사람이 주제 하나**를 맡아 진행합니다. 각자 공용 저장소의 `cases/<내 GitHub ID>-<주제>/` 폴더에 분석을 쌓고, 합쳐지면 [사이트](https://causalinferencelab.github.io/policy-effect-analytics-agent/)에 자동으로 올라갑니다.

## 먼저 볼 것

- [사이트 첫 화면](https://causalinferencelab.github.io/policy-effect-analytics-agent/): 궁금한 정책을 적으면 주제·관련 법령·데이터·분석 계획 초안을 대화로 정리해 줍니다.
- [지금 이슈](https://causalinferencelab.github.io/policy-effect-analytics-agent/issues.html): 논쟁 중인 정책 6개의 분석 가이드
- [데이터 지도](https://causalinferencelab.github.io/policy-effect-analytics-agent/data.html): 공공데이터 35개를 역할·단위·받는 법으로 정리
- 주제 페이지의 **관련 법령·행정규칙**: 법제처에서 근거 법률의 개정 이력, 지정·해제 공고, 관련 조례를 자동으로 모은 목록
- 분석 예시: [`cases/t3-land-permit-2025/`](../../cases/t3-land-permit-2025/) (토지거래허가구역, 지금은 시뮬레이션 데이터)
- 계획 쓰는 법: [`docs/strategy/plan-guide.md`](../strategy/plan-guide.md)

## 처음 한 번

```bash
git clone https://github.com/CausalInferenceLab/policy-effect-analytics-agent.git
cd policy-effect-analytics-agent
python -m venv .venv && source .venv/bin/activate    # Python 3.11 이상
pip install -e ".[dev]"
cp .env.example .env                                  # 받은 키를 여기에 (커밋되지 않음)
make demo                                             # 예시를 연습용 폴더에서 돌려 보기
```

## 혼자서 끝까지 가는 6단계

| 단계 | 할 일 | 결과물 |
|---|---|---|
| 1. 찾기 | 대화창·순위·지금 이슈에서 주제를 고릅니다 | "케이스 제안" 이슈 |
| 2. 모으기 | 그 주제의 정책을 모두 모읍니다. 주제 페이지의 법령 목록에서 시작일 후보를 찾고, 공식 발표로 확인합니다 | 정책 목록 표 |
| 3. 거르기 | 언제 시작했나 · 누가 받았나 · 무엇으로 재나를 확인합니다 | 이슈에 확인 결과 |
| 4. 계획하기 | `cp -r cases/_template cases/<내ID>-<주제>` 후 `plan.yaml`을 쓰고 **데이터를 보기 전에** PR | 계획 PR |
| 5. 비교하기 | `fetch.py`로 `data/panel.csv`를 만들고 `make flow CASE=cases/<내ID>-<주제>` | 수집·분석 PR |
| 6. 말하기 | `discussion.md`에 해석·한계를 쓰고 다시 `make flow` → `report.md`에 합쳐짐 | 리포트 PR |

"판단 불가"도 좋은 결과입니다. 왜 판단할 수 없는지가 분명하면 됩니다.

## 주차별 목표

| 모임 | 주차 | 끝낼 것 |
|---|---|---|
| OT 주간 | 1주 | 저장소 초대 수락, `make demo` 실행, 공공데이터포털·KOSIS 키 신청 |
| 9.27(일) | 2주 | 주제 후보 2개 고르기, 주제 페이지의 법령 목록으로 시작일 후보 확인 |
| 10.2(금) 오프라인 | — | 주제 1개 확정, `plan.yaml` 계획 PR |
| 10.4(일) | 3주 | `fetch.py`로 `data/panel.csv` 만들기, ③ 품질 점검 통과 |
| 10.11(일) | 4주 | 1차 추정과 추세 그림 (`make flow`) |
| 10.18(일) | 5주 | 반증 테스트 추가, `discussion.md` 초안 |
| 10.25(일) | 6주 | 과장 표현 점검 통과, 판정 문구 확정 |
| 11.1(일) | 7주 | 다른 멘티가 README만 보고 다시 돌려 보기 → 공개 |

지역마다 시작일이 다른 주제(시차 도입)는 전용 모듈이 4주차에, 정책 지역이 한두 곳뿐인 주제(합성통제)는 5주차에 들어옵니다. 그 전까지는 한 시점에 함께 시작한 지역만 골라 이중차분이나 단절 시계열로 1차 추정을 해 두세요.

## 폴더와 브랜치

```bash
git switch -c <내ID>/plan                           # 브랜치: <내 GitHub ID>/<작업>
cp -r cases/_template cases/<내ID>-<주제>           # 예: cases/gildong-local-currency
```

- `plan.yaml`의 `case_id`는 폴더 이름과 같아야 합니다.
- 수정은 **내 폴더만** 합니다. `core/`를 고쳐야 하면 먼저 이슈를 엽니다.
- `data/` 아래 파일은 git에 올라가지 않습니다. 데이터는 `fetch.py`로 각자 받게 합니다.
- PR 하나에 한 단계만 담고, 멘토 또는 다른 멘티 1명 승인 + 자동 검사 통과 뒤 합칩니다.

## 같이 보는 것 (담당자 없음, 모두)

- [사이트 질문](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/issues?q=is%3Aopen+label%3Afrom-site)과 [법령 변경 알림](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/issues?q=is%3Aopen+label%3Alaw-change)을 모임 전에 한 번씩 훑습니다.
- 내 주제와 관련 있으면 댓글을 달고, 새 주제·데이터·시작일이면 `catalog/`에 PR을 올립니다. 처리한 사람이 이슈를 닫습니다.

## 활동 인증

- 매 모임 전까지 내 브랜치에 커밋 1회 이상, PR 링크를 디스코드에 공유합니다.
- 멘토는 `python scripts/weekly_activity.py`로 케이스 폴더별 커밋을 확인합니다.

GitHub가 처음이라면 [github-onboarding.md](github-onboarding.md)를 따라 하세요.
