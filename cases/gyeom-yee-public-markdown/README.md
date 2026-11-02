# 행정안전부 'AI 친화적 보고서' 도입 효과 (gyeom-yee-public-markdown)

행정안전부가 2026년 3월 24일 공개한 'AI 친화적 보고서' 가이드라인(서술형 작성, 복잡한 표 지양, 마크다운 병행 제공)과 8월 24일 전면 실시가 행안부 **보도자료 형식**과 **기계 판독성**을 바꿨는지, 다른 중앙행정기관과 비교해 봅니다.

- 계획: [plan.yaml](plan.yaml) (사전 등록 0d173a9, 데이터 보기 전 수정 1aeda4c·dd002df)
- 결과: [report.md](report.md) (`make flow`가 만듭니다), 해석과 한계: [discussion.md](discussion.md)

## 다시 만들기

```bash
make install
pip install pdfplumber==0.11.4        # 기계 판독 표 손상률용 (MIT). 공통 의존성에는 넣지 않았습니다
make flow CASE=cases/gyeom-yee-public-markdown
python cases/gyeom-yee-public-markdown/extra_checks.py   # 결측 기관을 뺀 재추정 + 반박 검정 → extra_checks.json
```

`report.md`의 p값·신뢰구간은 공통 무작위화 추론이 결측 칸을 처리하지 못해 깨져 있습니다. 해석에는 `extra_checks.json`을 씁니다(자세한 내용은 [discussion.md](discussion.md)).

- `fetch.py`가 정책브리핑(korea.kr)에서 보도자료 목록·본문·첨부(HWPX·PDF)를 받습니다. API 키는 필요 없습니다.
- 처음 받을 때 한 시간 남짓 걸립니다(목록 약 1,500칸, 표본 약 5,000건). 보도자료별 지표만 `data/raw/`에 캐시하므로 끊겨도 다시 실행하면 이어서 받습니다. 원문과 첨부는 저장하지 않습니다.
- Windows에서는 `PYTHONUTF8=1`을 켜고 실행하세요.

## 패널 (`data/panel.csv`, 한 행 = 기관 × 월)

| 열 | 뜻 |
|---|---|
| `org_id`, `org_name`, `month`, `month_idx` | 정책브리핑 부처 코드, 기관명, 2024-01 = 0 … 2026-09 = 32 |
| `treated` | 행정안전부 = 1 |
| `releases` | 그 달 보도자료 건수 (전수, 가짜 지표) |
| `n_sampled`, `n_hwpx`, `n_pdf` | 표본 수(최대 5), 그중 HWPX가 있는 수, HWPX·PDF가 모두 있는 수 |
| `narrative_share` | 1차 지표. 표 밖 본문 문장·항목 중 '~다.'로 끝나는 비율 |
| `tables_per_release`, `nested_table_share` | 1건당 최상위 표 수, 표 안에 표가 있는 보도자료 비율 |
| `md_attach_share` | `.md` 첨부가 있는 보도자료 비율 (모든 칸이 0이라 추정에서 뺐습니다) |
| `parse_table_loss` | HWPX 표 셀 중 PDF(pdfplumber) 추출에서 같은 셀로 나오지 않은 비율 |

반박 검정용으로 과학기술정보통신부를 뺀 `data/panel_no_msit.csv`도 함께 만듭니다.
