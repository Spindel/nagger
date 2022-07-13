IMAGE_BUILD_FROM = registry.gitlab.com/modioab/base-image/fedora-$(FEDORA_ROOT_RELEASE)/python:master

IMAGE_REPO = registry.gitlab.com/modioab/nagger 
IMAGE_BUILD_VOLUME = $(realpath wheel)

# Run "nagger --help" as a self-test before publish
IMAGE_TEST_CMD = nagger --help
IMAGE_TEST_ARGS = -t


CLEANUP_FILES += wheel
# This allows CI to run without building wheels, even if the wheel-files dont match.
ifeq ($(HAVE_ARTIFACTS),)
IMAGE_FILES += wheel
endif

# This figures out the package name & version by calling setuptools. It allows
# us to know the exact name of the wheel file needed.
PKG_VERSION ?= $(shell python3 setup.py --version)
PKG_WHEEL   := nagger-${PKG_VERSION}-py3-none-any.whl

# a basic dep-chain so they at least re-build in development.
wheel/${PKG_WHEEL}: setup.cfg pyproject.toml nagger/*.py nagger/templates/*.py nagger/templates/*.md nagger/templates/*.txt
	pip wheel --wheel-dir=wheel .

.PHONY: wheel
wheel: wheel/${PKG_WHEEL}


include build.mk

check: ## check style with flake8
	flake8 nagger tests
	black --check nagger

test: ## run tests quickly with the default Python
	pytest

test-all: ## run tests on every Python version with tox
	tox
