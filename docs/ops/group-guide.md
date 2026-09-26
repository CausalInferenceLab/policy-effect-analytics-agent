# 조별 운영 가이드

조(약 5명)마다 공공데이터로 정책 효과 질문을 **하나** 정하고, 공용 저장소의 `cases/<조-주제>/` 폴더 하나에 결과를 쌓습니다.
전체 흐름은 6단계 에이전트 Flow(README의 Flow 절)와 같고, 조원 역할도 이 단계에 맞춰 나눕니다.

- 완성 예시: [`cases/_example_night_clinic/`](../../cases/_example_night_clinic/) — 합성 데이터로 6단계를 끝까지 돌린 샘플
- 주제 후보: [`docs/strategy/topic-guide.md`](../strategy/topic-guide.md) (T1~T8)
- 분석계획 작성법: [`docs/strategy/plan-guide.md`](../strategy/plan-guide.md)

## 1. 역할 (5인 기준, 겸임 가능)

| 역할 | 맡는 단계 | 주 산출물 |
|---|---|---|
| **문제 정의** (조장 겸임 권장) | ① 문제 정의 | `plan.yaml` — 질문·처치·대조·결과지표·가정·보류 규칙 |
| **데이터 수집** | ② 수집 | `fetch.py`, `data/README.md` (출처·라이선스·수집일) |
| **지표·품질** | ③ 지표 구조화 | 정제 패널(`data/panel.csv`), 품질 점검 통과 |
| **추정** | ④ 효과 추정 | `estimate.py`, 사전추세·placebo 결과 |
| **리포트·에이전트** | ⑤ 과잉해석 방지, ⑥ 리포트 | `report.md`, 그림, `flow_log.json` |

4명 이하면 **수집 + 지표·품질**, **추정 + 리포트**를 한 사람이 맡습니다. 역할은 주마다 바꿔도 됩니다.

## 2. 주차별 마일스톤

| 모임 | 주차 | 조가 끝낼 것 | 인증(커밋/PR) |
|---|---|---|---|
| 9.27(일) | W2 | 조 편성, 주제 후보 2개 선택, 데이터 접근 확인(API 키 발급) | `cases/<조>/` 폴더 + 이슈 "케이스 제안" |
| 10.2(금) 오프라인 | — | 주제 1개 확정, **`plan.yaml` 사전 등록 PR** | plan.yaml PR 병합 |
| 10.4(일) | W3 | `fetch.py` 동작, ③ 품질 점검 통과 | 수집·정제 PR |
| 10.11(일) | W4 | ④ 1차 추정 + 사전추세 그림 | 추정 PR |
| 10.18(일) | W5 | 반박 검정 추가, 에이전트 Flow로 ①~⑥ 한 번에 실행 | `flow_log.json` 커밋 |
| 10.25(일) | W6 | ⑤ 가드 통과(과잉 인과 표현 제거), 판정 문구 확정 | 리포트 PR |
| 11.1(일) | W7 | 다른 조가 README만 보고 재현 성공 → 공개 | 교차 재현 결과 이슈 |

Level 1(정리된 데이터 + 문서)에서 멈춰도 산출물입니다. 판정이 "식별 불가"로 나와도 근거가 명확하면 좋은 결과입니다.

## 3. 브랜치·PR 규칙

- 브랜치: `group<N>/<짧은-설명>` (예: `group2/fetch-airkorea`). `main`에 직접 push 하지 않습니다.
- 수정 범위: **자기 조 `cases/<조>/` 폴더만.** `core/` 수정이 필요하면 이슈를 먼저 엽니다.
- **사전 등록**: `plan.yaml`을 먼저 PR로 병합한 뒤 데이터를 봅니다. Flow ①단계가 커밋되지 않은 plan.yaml을 막습니다.
- PR 하나에 한 단계. 리뷰 1명 승인 + CI 통과 후 병합(Squash).
- 올리면 안 되는 것: API 키(`.env`), 원자료 대용량 파일(`data/raw/`), 개인정보가 담긴 데이터, 재배포가 금지된 데이터(라이선스 확인).

## 4. 실행 방법

```bash
make install                                   # 최초 1회
cp -r cases/_template cases/group1-topic       # 조 폴더 만들기
make flow CASE=cases/group1-topic               # ①~⑥ 실행 (plan.yaml 커밋 후)
make app                                        # Streamlit → Flow 페이지에서 단계별 결과 확인
```

## 5. 활동 인증

- 매 모임 전까지 조 브랜치에 커밋 1회 이상 + PR 링크를 디스코드 조 채널에 공유합니다.
- 멘토는 `python scripts/weekly_activity.py`로 조별 커밋·변경 파일을 확인합니다 ([monitoring.md](monitoring.md)).
- 조모임은 전체 모임과 별도로 자유롭게 잡고, 결정 사항은 PR 설명이나 이슈에 남깁니다.
