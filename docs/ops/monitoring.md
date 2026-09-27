# 활동 확인 (멘토용)

원칙: **커밋과 PR이 곧 출석**입니다. 멘티마다 주 1회 이상 의미 있는 커밋과 PR 흐름이 보이면 건강한 상태입니다.

## 로컬에서 한 번에 보기

```bash
git fetch --all
python scripts/weekly_activity.py              # 최근 7일, 모든 브랜치
python scripts/weekly_activity.py --days 14 --ref origin/main
```

출력: 케이스 폴더(`cases/<ID>-<주제>`)별 커밋 수 · 작성자 · 변경 파일 수 · 추가/삭제 줄 수. 활동이 없는 폴더는 `<- no activity`로 표시됩니다.

## gh 명령으로 보기

```bash
R=CausalInferenceLab/policy-effect-analytics-agent
SINCE=$(date -d '7 days ago' +%F)

# 열린 PR 전체
gh pr list -R $R --state open

# 한 멘티의 브랜치 PR (브랜치 이름 = <ID>/<작업>)
gh pr list -R $R --state all --json headRefName,author,title,state \
  --jq '.[] | select(.headRefName|startswith("gildong/")) | [.state,.author.login,.title] | @tsv'

# 한 멘티 폴더의 최근 커밋
gh api "repos/$R/commits?path=cases/gildong-local-currency&since=${SINCE}T00:00:00Z" \
  --jq '.[] | [.commit.author.date,.commit.author.name,.commit.message] | @tsv'

# 사이트 대화창에서 올라온 질문, 법령 변경 알림
gh issue list -R $R --label from-site
gh issue list -R $R --label law-change
```

## 건강 신호

| 항목 | 건강 | 확인 필요 |
|---|---|---|
| 주간 커밋 | 2개 이상 | 0개 |
| 계획 PR | 10.2까지 `plan.yaml` 합쳐짐 | 계획 없이 결과 먼저 |
| 리뷰 | PR이 3일 안에 리뷰됨 | 1주 넘게 대기 |
| CI | 초록 | 빨간 채로 방치 |

## 주간 루틴

1. `git fetch --all && python scripts/weekly_activity.py` → 조용한 폴더 확인
2. 열린 PR 리뷰, 3일 넘은 PR에 코멘트
3. `from-site`·`law-change` 이슈는 구성원 모두가 봅니다. 멘토는 한 주 넘게 댓글이 없는 것만 챙깁니다
