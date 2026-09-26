PYTHON ?= .venv/bin/python
export PYTHONPATH := src

.PHONY: setup app test lint format research
setup:
	uv venv --allow-existing .venv
	uv pip install --python $(PYTHON) -e '.[dev]'
app:
	$(PYTHON) -m streamlit run streamlit_app.py
test:
	$(PYTHON) -m pytest -q
lint:
	$(PYTHON) -m ruff check .
format:
	$(PYTHON) -m ruff format .
research:
	$(PYTHON) scripts/refresh_research.py
