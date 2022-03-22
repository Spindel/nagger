IMAGE_BUILD_FROM = registry.gitlab.com/modioab/base-image/fedora-$(FEDORA_ROOT_RELEASE)/python:master

ARCHIVE_PREFIX = /srv/app/
SOURCE_ARCHIVE = nagger.tar
IMAGE_FILES += $(SOURCE_ARCHIVE)

IMAGE_REPO = registry.gitlab.com/modioab/nagger 
include build.mk

check: ## check style with flake8
	flake8 nagger tests
	black --check nagger

test: ## run tests quickly with the default Python
	pytest

test-all: ## run tests on every Python version with tox
	tox
