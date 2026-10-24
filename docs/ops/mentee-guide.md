# 멘티 참여 가이드

커리어 방향과 해 보고 싶은 시도에 따라 **세 가지 방식** 중 하나로 기여합니다. 각자 공용 저장소의 내 폴더에 작업을 쌓고, 합쳐지면 [사이트](https://causalinferencelab.github.io/policy-effect-analytics-agent/)에 자동으로 올라갑니다.

| 트랙 | 이런 분께 | 하는 일 | 내 작업 공간 | 가이드 |
|---|---|---|---|---|
| **A. 데이터 온톨로지** | 데이터 온톨로지를 만들고 싶다 | 공공 이슈와 연결되는 데이터를 찾고 계보(Lineage) 구축 | `catalog/lineage/<내ID>-<주제>.yaml` | [ontology.md](../tracks/ontology.md) |
| **B. 가설과 분석** | 가설 설정과 분석을 익히고 싶다 | 실제 사례로 효과를 추정하는 Cycle 연습 | `cases/<내ID>-<주제>/` | [analysis.md](../tracks/analysis.md) |
| **C. 서비스 개발** | 서비스를 개발하고 싶다 | 분석 Cycle에서 나온 데이터로 웹·앱 서비스 개발 | `apps/<내ID>-<서비스>/` | [service.md](../tracks/service.md) |

세 트랙은 이어져 있습니다. A가 이슈와 데이터를 이으면 B가 그 데이터로 효과를 추정하고, B의 결과(공개 API)로 C가 서비스를 만듭니다. 전체 그림: [docs/tracks/README.md](../tracks/README.md)

**시작은 모두 같습니다**: [작업 제안 이슈](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/issues/new?template=case-proposal.yml)에서 트랙과 주제를 적고, 내 ID로 브랜치를 만듭니다.

## 먼저 볼 것

- [참여자 프로젝트](https://causalinferencelab.github.io/policy-effect-analytics-agent/projects.html): 누가 어떤 정책을 어디까지(계획 → 수집 → 분석 → 해석) 진행했는지, 열린 PR·작업 제안까지 한 화면에
- [사이트 첫 화면](https://causalinferencelab.github.io/policy-effect-analytics-agent/): 궁금한 정책을 적으면 주제·관련 법령·데이터·분석 계획 초안을 대화로 정리해 줍니다.
- [지금 이슈](https://causalinferencelab.github.io/policy-effect-analytics-agent/issues.html): 논쟁 중인 정책 7개의 분석 가이드 (기후동행카드 예시: [climate-card.md](../strategy/climate-card.md))
- [데이터 지도](https://causalinferencelab.github.io/policy-effect-analytics-agent/data.html): 공공데이터 40개를 역할·단위·받는 법으로 정리
- [데이터 계보](https://causalinferencelab.github.io/policy-effect-analytics-agent/lineage.html): 이슈 → 정책 → 데이터 → 지표 → 분석의 연결과 주제별 빈칸 (트랙 A)
- [서비스](https://causalinferencelab.github.io/policy-effect-analytics-agent/apps.html): 공개 API와 서비스 템플릿 (트랙 C)
- 주제 페이지의 **관련 법령·행정규칙**: 법제처에서 근거 법률의 개정 이력, 지정·해제 공고, 관련 조례를 자동으로 모은 목록
- 분석 예시: [`cases/t3-climate-card-seongnam/`](../../cases/t3-climate-card-seongnam/) (기후동행카드 성남 편입, **실데이터 · 키 불필요**), [`cases/t3-land-permit-2025/`](../../cases/t3-land-permit-2025/) (토지거래허가구역, 지금은 시뮬레이션 데이터)
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

## 트랙 B: 효과를 추정하는 6단계

| 단계 | 할 일 | 결과물 |
|---|---|---|
| 1. 찾기 | 대화창·순위·지금 이슈에서 주제를 고릅니다 | "작업 제안" 이슈 |
| 2. 모으기 | 그 주제의 정책을 모두 모읍니다. 주제 페이지의 법령 목록에서 시작일 후보를 찾고, 공식 발표로 확인합니다 | 정책 목록 표 |
| 3. 거르기 | 언제 시작했나 · 누가 받았나 · 무엇으로 재나를 확인합니다 | 이슈에 확인 결과 |
| 4. 계획하기 | `cp -r cases/_template cases/<내ID>-<주제>` 후 `plan.yaml`을 쓰고 **데이터를 보기 전에** PR | 계획 PR |
| 5. 비교하기 | `fetch.py`로 `data/panel.csv`를 만들고 `make flow CASE=cases/<내ID>-<주제>` | 수집·분석 PR |
| 6. 말하기 | `discussion.md`에 해석·한계를 쓰고 다시 `make flow` → `report.md`에 합쳐짐 | 리포트 PR |

"판단 불가"도 좋은 결과입니다. 왜 판단할 수 없는지가 분명하면 됩니다.

## 주차별 목표

| 모임 | 주차 | 공통 |
|---|---|---|
| OT 주간 | 1주 | 저장소 초대 수락, `make demo` 실행, 공공데이터포털·KOSIS 키 신청 |
| 9.27(일) | 2주 | 주제 후보 2개 고르기, 주제 페이지의 법령 목록으로 시작일 후보 확인 |
| 10.2(금) 오프라인 | — | 주제 1개 확정 |
| 10.18(일) | 5주 | **트랙 선택** — 작업 제안 이슈에 트랙(A·B·C)과 주제 적기 |

남은 2주는 트랙별로 갑니다.

| 모임 | A. 데이터 온톨로지 | B. 가설과 분석 | C. 서비스 개발 |
|---|---|---|---|
| 10.25(일) | 이슈 하나의 계보 YAML PR (`make lineage` 통과) | `plan.yaml` PR + `fetch.py`로 `data/panel.csv` | `apps/<내ID>-<서비스>/` 첫 화면 PR (API 하나 이상) |
| 11.1(일) 공개 | 새 데이터셋 1개 이상 추가, 계보가 사이트에 표시 | `make flow` 결과 + `discussion.md`, 다른 멘티가 재현 | 기능 1개 완성 + README, 사이트에서 열림 |

트랙 B에서 지역마다 시작일이 다르거나(시차 도입) 정책 지역이 1~5곳(합성통제)이면 전용 모듈이 아직 준비 중입니다. 그 전까지는 같은 날 시작한 지역만 고르거나 무작위화 추론으로 1차 추정하고 한계에 적습니다.

## 폴더와 브랜치

```bash
git switch -c <내ID>/<작업>                               # 브랜치: <내 GitHub ID>/<작업>
cp catalog/lineage/_template.yaml catalog/lineage/<내ID>-<주제>.yaml   # A
cp -r cases/_template cases/<내ID>-<주제>                 # B (예: cases/gildong-local-currency)
cp -r apps/_template apps/<내ID>-<서비스>                 # C (예: apps/gildong-policy-alarm)
```

- 계보의 `id`, 케이스의 `case_id`는 파일·폴더 이름과 같아야 합니다.
- 새 케이스를 만들면 `catalog/projects.yaml`에 한 줄(담당자·트랙·주제·작업 제안 이슈 번호)을 추가합니다. 그래야 프로젝트 화면과 주제 페이지에 주제와 함께 나옵니다.
- 수정은 **내 파일·폴더만** 합니다. `catalog/datasets.yaml` 추가는 누구나 PR로 합니다. `core/`·`site/`를 고쳐야 하면 먼저 이슈를 열고 따로 PR을 올립니다.
- `data/` 아래 파일은 git에 올라가지 않습니다. 데이터는 `fetch.py`로 각자 받게 합니다.
- PR 하나에 한 단계만 담고, 멘토 또는 다른 멘티 1명 승인 + 자동 검사 통과 뒤 합칩니다.

## 같이 보는 것 (담당자 없음, 모두)

- [사이트 질문](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/issues?q=is%3Aopen+label%3Afrom-site)과 [법령 변경 알림](https://github.com/CausalInferenceLab/policy-effect-analytics-agent/issues?q=is%3Aopen+label%3Alaw-change)을 모임 전에 한 번씩 훑습니다.
- 내 주제와 관련 있으면 댓글을 달고, 새 주제·데이터·시작일이면 `catalog/`에 PR을 올립니다. 처리한 사람이 이슈를 닫습니다.

## 활동 인증

- 매 모임 전까지 내 브랜치에 커밋 1회 이상, PR 링크를 디스코드에 공유합니다.
- 멘토는 `python scripts/weekly_activity.py`로 케이스 폴더별 커밋을 확인합니다.

GitHub가 처음이라면 [github-onboarding.md](github-onboarding.md)를 따라 하세요.
