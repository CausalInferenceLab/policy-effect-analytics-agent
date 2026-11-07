.PHONY: install check lint test format app activity flow demo site lineage readme pywhy draft

PY ?= python

# .env 가 있으면 키를 환경변수로 불러온다 (.env 는 커밋 금지)
-include .env
export

install:
	$(PY) -m pip install -e ".[dev]"

check: lint test

lint:
	$(PY) -m ruff check .

test:
	$(PY) -m pytest -q

format:
	$(PY) -m ruff format . && $(PY) -m ruff check --fix .

# 내 케이스를 여섯 단계로 실행. plan.yaml 이 커밋되어 있어야 계산한다(사전 등록).
CASE ?= cases/_example_night_clinic
flow:
	$(PY) -m core.agent $(CASE)

# 두 번째 의견: PyWhy(DoWhy) 식별·반박 검정 + CausalML 단위별 효과 → cases/<케이스>/pywhy_check.json
#   먼저 pip install -e ".[causal]"
pywhy:
	$(PY) -m core.causal $(CASE)

# 질문 한 줄 → 가설·데이터 점검 → plan.yaml 초안 (Q="질문", NEW=<내ID>-<주제> 를 주면 cases/ 에 저장)
draft:
	$(PY) -m core.causal.draft "$(Q)" $(if $(NEW),--case $(NEW) --write,)

# 연습: 토지거래허가구역 예시를 _demo/ 에 복사해 돌린다. 레포 파일은 바뀌지 않는다.
demo:
	rm -rf _demo && mkdir -p _demo && cp -r cases/t3-land-permit-2025 _demo/
	$(PY) -m core.agent _demo/t3-land-permit-2025 --allow-uncommitted

# 트랙 A: 데이터 계보(catalog/lineage/*.yaml) 검사
lineage:
	$(PY) scripts/check_lineage.py

# 사이트 미리보기: http://localhost:8000 (공개 API /api/, 서비스 /apps/)
site:
	$(PY) site/build.py && $(PY) -m http.server -d _site

# README 의 '지금까지 만든 것' 표를 레포 파일에서 다시 만들기
readme:
	$(PY) scripts/readme_highlights.py

# (선택) 개발용 Streamlit 화면: pip install -e ".[app]"
app:
	streamlit run app/streamlit_app.py

activity:
	$(PY) scripts/weekly_activity.py --days 7
