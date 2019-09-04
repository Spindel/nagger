ARCHIVE_PREFIX = /srv/app/
SOURCE_ARCHIVE = nagger.tar
IMAGE_FILES += $(SOURCE_ARCHIVE)

IMAGE_REPO = registry.gitlab.com/spindel/nagger 
include build.mk

check: ## check style with flake8
	flake8 nagger tests
	black --check nagger

test: ## run tests quickly with the default Python
	python3 setup.py test

test-all: ## run tests on every Python version with tox
	tox
