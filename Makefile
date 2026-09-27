.PHONY: install check lint test format app activity flow demo site

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

# 연습: 토지거래허가구역 예시를 _demo/ 에 복사해 돌린다. 레포 파일은 바뀌지 않는다.
demo:
	rm -rf _demo && mkdir -p _demo && cp -r cases/t3-land-permit-2025 _demo/
	$(PY) -m core.agent _demo/t3-land-permit-2025 --allow-uncommitted

# 사이트 미리보기: http://localhost:8000
site:
	$(PY) site/build.py && $(PY) -m http.server -d _site

# (선택) 개발용 Streamlit 화면: pip install -e ".[app]"
app:
	streamlit run app/streamlit_app.py

activity:
	$(PY) scripts/weekly_activity.py --days 7
