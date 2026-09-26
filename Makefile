PYTHON ?= .venv/bin/python
CSV ?= data/raw/complaints.csv
DATA_DIR ?= data
ENFORCEMENT_ARGS ?=
PIPELINE_ARGS ?=
RESOLVE_ARGS ?=
export PYTHONPATH := src

.PHONY: setup ingest delta test lint format fdic enforcement hmda-spike resolve pipeline
setup:
	uv venv --allow-existing .venv
	uv pip install --python $(PYTHON) -e '.[dev]'
ingest:
	$(PYTHON) -m ews.ingest.complaints ingest --csv "$(CSV)" --data-dir "$(DATA_DIR)"
delta:
	$(PYTHON) -m ews.ingest.complaints delta --data-dir "$(DATA_DIR)"
test:
	$(PYTHON) -m pytest
lint:
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m black --check src tests
format:
	$(PYTHON) -m ruff check --fix src tests
	$(PYTHON) -m black src tests
fdic:
	$(PYTHON) -m ews.ingest.fdic
enforcement:
	$(PYTHON) -m ews.ingest.enforcement --data-dir "$(DATA_DIR)" $(ENFORCEMENT_ARGS)
hmda-spike:
	$(PYTHON) -m ews.ingest.hmda
resolve:
	$(PYTHON) -m ews.resolve.pipeline --data-dir "$(DATA_DIR)" $(RESOLVE_ARGS)

pipeline:
	$(PYTHON) -m ews.pipeline --data-dir "$(DATA_DIR)" $(PIPELINE_ARGS)
