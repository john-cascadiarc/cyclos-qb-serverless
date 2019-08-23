.PHONY: help dev test lint run doc clean venv

VENV_NAME?=venv
VENV_ACTIVATE=. $(VENV_NAME)/bin/activate
PYTHON=${VENV_NAME}/bin/python

.DEFAULT: help
help:
	@echo "make prepare-dev"
	@echo "       prepare development environment, use only once"
	@echo "make test"
	@echo "       run tests"

venv: $(VENV_NAME)/bin/activate
$(VENV_NAME)/bin/activate: requirements.txt
	test -d $(VENV_NAME) || python3 -m venv $(VENV_NAME)
	. venv/bin/activate ;\
	pip install -r requirements.txt
	touch $(VENV_NAME)/bin/activate

dev: venv dev-requirements
dev-requirements: dev-requirements.txt
	. $(VENV_NAME)/bin/activate ;\
	pip install -r dev-requirements.txt

test: dev
	${PYTHON} -m unittest discover -s tests -v

clean: 
	rm -rf $(VENV_NAME)