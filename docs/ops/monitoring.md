# 활동 모니터링 (멘토·PM용)

원칙: **커밋·PR이 곧 출석**입니다. 조별로 주 1회 이상 의미 있는 커밋과 PR 흐름이 보이면 건강한 상태입니다.

## 1. 로컬 스크립트 (네트워크 불필요)

```bash
git fetch --all --prune                      # 병합 전 브랜치까지 포함하려면 먼저
python scripts/weekly_activity.py            # 최근 7일, 모든 브랜치
python scripts/weekly_activity.py --days 14 --ref origin/main   # main에 반영된 것만
make activity
```

출력: `cases/<조>`별 커밋 수·작성자 수·변경 파일 수·추가/삭제 줄 수. 활동 없는 조는 `<- no activity` 표시.

## 2. `gh` CLI 한 줄 명령

```bash
R=CausalInferenceLab/policy-effect-analytics-agent
SINCE=$(date -d '7 days ago' +%F 2>/dev/null || date -v-7d +%F)   # Linux || macOS

# 이번 주 열린/병합된 PR
gh pr list -R $R --state all --search "created:>=$SINCE" --limit 100
gh pr list -R $R --state merged --search "merged:>=$SINCE"

# 리뷰 대기 중인 PR (오래된 순)
gh pr list -R $R --search "is:open review:required sort:created-asc"

# 조별 브랜치의 PR (브랜치 prefix = 조)
gh pr list -R $R --state all --json headRefName,title,state,author \
  --jq '.[] | select(.headRefName|startswith("group3/")) | [.state,.author.login,.title] | @tsv'

# 이번 주 main 커밋 작성자별 수
gh api "repos/$R/commits?since=${SINCE}T00:00:00Z&per_page=100" --paginate \
  --jq '.[].author.login' | sort | uniq -c | sort -rn

# 특정 조 폴더의 커밋
gh api "repos/$R/commits?path=cases/group3-youth-rent&since=${SINCE}T00:00:00Z" \
  --jq '.[] | [.commit.author.date[:10], .author.login, .commit.message] | @tsv'

# CI 실패 현황
gh run list -R $R --status failure --limit 20

# 케이스 제안 이슈
gh issue list -R $R --label case-proposal --state all
```

## 3. "건강함"의 기준

| 지표 | 건강 | 주의 (멘토링 필요) |
|---|---|---|
| 조별 주간 커밋 | 3개 이상, 2명 이상 작성자 | 0개 또는 1명만 커밋 |
| PR 흐름 | 주 1개 이상 병합 | 7일 넘게 열린 PR, 리뷰 없음 |
| CI | 병합 전 초록 | 같은 PR에서 3회 이상 연속 실패 |
| 사전 등록 | 2주차에 `plan.yaml` 병합 | 결과 그림이 plan.yaml보다 먼저 커밋 |
| 데이터 위생 | `data_sources.license` 기재 | 대용량/원자료 커밋, `.env` 흔적 |

## 4. 주간 루틴 (15분)

1. `git fetch --all && make activity` → 조용한 조 확인
2. `gh pr list ... review:required` → 오래된 PR 리뷰 배정
3. `gh run list --status failure` → 반복 실패 조에 도움 요청 코멘트
4. 결과를 주간 공지(노션/채널)에 3줄 요약
