# T3. 기후동행카드 성남 편입(2025.5.3) → 성남 역 평일 승차

> 실데이터(서울 열린데이터광장 OA-12914)로 돌린 멘토 예시입니다. 단, **탐색 분석으로 결과를 먼저 본 뒤 쓴 계획**이라 사전 등록이 아닙니다. 사전 등록 연습은 [다음 가설](../../docs/strategy/climate-card.md#6-데이터로-본-첫-결과-탐색-분석-2026-10-18)로 하세요.

**흐름**: 지금 이슈 `climate-card-expansion-2024` → [데이터 계보](../../catalog/lineage/climate-card-expansion.yaml)(역 처치표 → 역×주 패널 → 평일 승차 지표) → 이 분석 → [공개 API](https://causalinferencelab.github.io/policy-effect-analytics-agent/api/results.json)

| 항목 | 내용 |
|---|---|
| 처치 | 성남 수인분당선 야탑~가천대 10역 · 경강선 판교·이매 (2025-05-03 적용, 첫 처치 주 2025-05-05) |
| 대조 | 같은 분당선 용인·수원 구간 + 경부선 수원 구간 16역 (분석 기간 미적용) |
| 기간 | 2024-11-04 주 ~ 2025-10-27 주 (적용 전 26주 · 후 26주, 전환 주 제외) |
| 결과 | 평일(공휴일 제외) 하루 평균 승차(로그, 1차) · 하차(로그) |
| 추정 | 이벤트 스터디(역 고정효과 + 주 고정효과), 역 군집 표준오차, 가짜 시점(8주 앞) |
| 판정 | **판단 불가** — 평균 +0.4% [-3.5, +4.5], 사전 계수 ±1.2% 안이지만 결합 검정 기각(p=0.005). 해석: [discussion.md](discussion.md) |

## 실행

```bash
pip install -e ".[dev,analysis]"                  # holidays 포함
make flow CASE=cases/t3-climate-card-seongnam     # fetch.py 가 월별 파일 13개(약 16MB)를 data/raw/subway/ 에 받습니다
```

- 키가 필요 없습니다. 원자료(`data/raw/`)와 패널(`data/panel.csv`)은 커밋되지 않습니다.
- 역 목록은 `catalog/lineage/data/climate-card-stations.csv` 하나에서 읽습니다. 역을 바꾸려면 이 파일과 계보를 함께 고칩니다(`make lineage`).
- 네 도시(고양·과천·성남·하남)를 한 번에 보는 탐색 분석: `python scripts/explore_climate_card.py`

## 이 예시를 이어받는 법

| 트랙 | 할 일 |
|---|---|
| B. 가설과 분석 | 이 폴더를 복사해 `cases/<내ID>-climate-card-<가설>/`로 만들고, **결과를 보기 전에** `plan.yaml`을 커밋 (H8 고양 GTX 영향 역 제외, H9 하남 ↔ 강일·상일동 이동, H10 출퇴근 시간대) |
| A. 데이터 온톨로지 | 계보의 빈칸(권종별 승하차 자료, 김포골드라인 역 자료)을 찾아 `datasets.yaml`·계보에 추가 |
| C. 서비스 개발 | `api/results.json`의 이 케이스 결과와 `api/lineage.json`으로 "우리 동네 역은 편입 뒤 어떻게 됐나" 화면 |
