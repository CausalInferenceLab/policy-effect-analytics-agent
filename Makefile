.PHONY: install check lint test format app activity

PY ?= python

install:
	@command -v uv >/dev/null 2>&1 && uv pip install -e ".[dev]" || $(PY) -m pip install -e ".[dev]"

check: lint test

lint:
	ruff check .

test:
	pytest -q

format:
	ruff format . && ruff check --fix .

app:
	streamlit run app/streamlit_app.py

activity:
	$(PY) scripts/weekly_activity.py --days 7
