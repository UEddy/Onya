PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: eval
eval:
	$(PYTHON) scripts/eval_backtest.py
