# data/

| 파일 | 내용 | 출처 / 라이선스 |
|---|---|---|
| `panel.csv` | **합성** 시군구×연도 패널 (`region_id, year, treated, first_treat, night_ed_rate`) | `simulate_panel(seed=42)` / synthetic |
| `panel.source.json` | 생성 파라미터·시각 (재현용) | — |

## 실데이터 후보 (각자 확인 필요 — 가용성·공간단위·라이선스 미검증)
- **처치 시점**: 보건복지부/지자체 달빛어린이병원 지정 현황 (공공데이터포털 파일데이터 또는 보도자료)
- **결과변수**: 국가응급진료정보망(NEDIS) 기반 응급실 이용 통계 — 시군구·시간대·KTAS 단위 공개 여부 확인 필요.
  공개 수준이 시도 단위뿐이면 클러스터가 17개 → `few_clusters` 경고 대상
- **분모**: KOSIS 주민등록인구(0~14세) — `core.adapters.KosisAdapter` (`KOSIS_API_KEY` 필요)

원천 데이터는 가능하면 커밋하지 말고 `fetch.py` 로 재생성합니다. 크기가 작고 라이선스가 허용(공공누리 1유형 등)하면 스냅샷 커밋 가능.
