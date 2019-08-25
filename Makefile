.PHONY: help dev test deploy clean venv

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

dev-requirements: tests/dev-requirements.txt
	. $(VENV_NAME)/bin/activate ;\
	pip install -r tests/dev-requirements.txt
	touch tests/dev-requirements.txt

test: dev
	${PYTHON} -W ignore:ResourceWarning -m unittest discover -s tests -vvv

clean: 
	rm -rf $(VENV_NAME)

deploy: 
	sls deploy