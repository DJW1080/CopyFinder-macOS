PYTHON := /usr/bin/python3

.PHONY: run test package
run:
	$(PYTHON) -m copyfinder

test:
	$(PYTHON) -m unittest discover -s tests -v

package:
	$(PYTHON) scripts/build_deb.py
