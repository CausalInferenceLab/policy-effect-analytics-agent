# 결과 검토 체크리스트

사이트의 판정은 '이 데이터와 이 비교로는'이라는 조건이 붙은 답입니다. 작성자가 아닌 사람이 아래 여덟 가지를 확인하면 그 결과에 **검토됨** 배지가 붙습니다.
검토는 결과가 맞다는 보증이 아니라, 결과가 **자기 규칙을 지켰다**는 확인입니다. 숫자를 다시 돌려 보는 것은 [교차 재현](../../.github/ISSUE_TEMPLATE/reproduction.yml)이 따로 맡습니다.

| # | 확인할 것 | 어디서 보나 | 통과 기준 |
|---|---|---|---|
| 1 | 계획이 결과보다 먼저인가 | 답 페이지 '이 결과를 얼마나 믿을 수 있나' · `git log -- cases/<케이스>/plan.yaml` | 계획 먼저 커밋, 또는 결과 뒤 수정 이유가 discussion.md '계획에서 바뀐 것'에 있음 |
| 2 | 처치 시점이 공식 문서로 확인되나 | plan.yaml `treatment.definition` · README | 법령·고시·보도자료·조례 중 하나의 링크 |
| 3 | 비교 대상이 결과를 보고 고른 것이 아닌가 | plan.yaml `control.rationale` · fetch.py | 선정 규칙이 코드나 문장으로 고정돼 있음 |
| 4 | 데이터 이용 조건이 공개에 맞나 | plan.yaml `data_sources[].license` | 공공누리 1유형·이용허락 제한 없음, 또는 원자료를 커밋하지 않음 |
| 5 | 원자료·개인정보·키가 레포에 없나 | PR 파일 목록 | `data/`·`.env`·키 없음 |
| 6 | 판정 문장이 판정을 넘지 않나 | discussion.md '결과를 한 문장으로' · README | '크기를 판별하지 못함'·'판단 불가'를 '효과 없음'으로 쓰지 않음, 인과 단정 없음 |
| 7 | 한계가 적혀 있나 | discussion.md · plan.yaml `cautions` | 동시에 일어난 다른 사건, 대조군 오염, 측정 문제 중 해당하는 것 |
| 8 | 지표 정의가 재현 가능한가 | plan.yaml `outcomes[].definition` · fetch.py | 다른 사람이 같은 표를 만들 수 있을 만큼 구체적임 |

## 절차

검토 짝은 사이트 [참여](https://causalinferencelab.github.io/policy-effect-analytics-agent/projects.html#review) 화면의 '검토 짝'에 자동으로 제안됩니다(결과를 낸 다른 참여자를 돌아가며).

1. 결과 PR에서 위 표를 복사해 PR 리뷰 댓글에 ✅/❌로 채웁니다. ❌가 있으면 작성자가 고친 뒤 다시 봅니다.
2. 여덟 개가 모두 ✅면 `catalog/projects.yaml`의 그 케이스에 `reviewed_by: [내 GitHub ID]`를 더하는 커밋을 같은 PR에 올립니다.
3. 사이트가 다시 빌드되면 결과 카드·검색 판정 패널에 **검토됨**, 답 페이지 신뢰 항목에 '검토 · 통과'가 나옵니다.

작성자 본인은 자기 결과를 검토할 수 없습니다. 멘토 예시도 같은 규칙을 따릅니다.

## 뉴스 주장 검토 기록

검색 화면에 뉴스 문장을 붙여 넣어 나온 판정은 '실제 기사·발표의 주장이면 검토 기록으로 남기기'로 [주장 검토 이슈](../../.github/ISSUE_TEMPLATE/claim-review.yml)가 됩니다.
검토자가 주장 원문·출처·날짜와 분석의 지역·기간·지표가 맞는지 확인한 뒤 `catalog/projects.yaml` 의 그 케이스 `claims:` 에 한 줄을 더하면, 답 페이지에 schema.org ClaimReview 가 붙습니다.
