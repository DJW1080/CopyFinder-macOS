PYTHON ?= python3

.PHONY: run test package
run:
	$(PYTHON) -m copyfinder

test:
	$(PYTHON) scripts/run_tests.py

package:
	$(PYTHON) scripts/build_macos.py
