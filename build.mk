# build.mk --- Makefile include for building container images

# Copyright (C) 2018-2020 Modio AB

# https://gitlab.com/ModioAB/build.mk/

# Copying and distribution of this file, with or without modification,
# are permitted in any medium without royalty provided the copyright
# notice and this notice are preserved. This file is offered as-is,
# without any warranty.


######################################################################
### Usage
######################################################################

## By setting certain variables before including build.mk in your
## makefile you can set up some commonly used make rules for building
## container images.

## Variables with uppercase names are used as the public interface
## for build.mk.
##
## Variables with lowercase names are considered private to the
## including makefile.
##
## Variables having names starting with underscore are considered
## private to build.mk.


## The fallback default goal does nothing. Set the variable
## .DEFAULT_GOAL to change the default goal for your makefile, or
## specify a rule before including build.mk if that is appropriate.

default:


## Set V=1 to echo the make recipes. Recipes are always echoed for CI
## builds.

ifeq ($(CI),)
ifneq ($(V),1)
Q = @
endif
endif


# Workaround for problem with podman registry authentication. libpod
# prefers to store its login credentials in
# /var/run/container/$UID/auth.json, but only seems to successfully
# find them in $HOME/.docker/config.json .
ifneq ($(CI),)
REGISTRY_AUTH_FILE ?= $(HOME)/.docker/config.json
export REGISTRY_AUTH_FILE
endif

# MAKEFILE_LIST needs to be checked before any includes are processed.
_buildmk_path := $(lastword $(MAKEFILE_LIST))

# In the rare case that stdout is a TTY while TERM is not set, provide
# a fallback.
TERM ?= dumb

_tput = $(shell command -v tput)
ifneq ($(_tput),)
_log_before = if test -t 1; then $(_tput) -T $(TERM) setaf 14; fi
_log_after = if test -t 1; then $(_tput) -T $(TERM) sgr0; fi
else
_log_before = :
_log_after = :
endif

# $(call _cmd,example) expands to the contents of _cmd_example
# variable. It should contain a series of commands suitable for a make
# recipe. Each command in the variable should be preceded with $(Q).
#
# If there is a _log_cmd_example variable, it will be expanded into a
# printf-command that precedes the commands from the _cmd_example
# variable. This printf will produce output even if the commands of
# the recipe aren't echoed.
#
# The "define" command may be used to assign multiple-line values to
# variables:
#
# define _cmd_example =
# $(Q)rot13 < $< > $@
# endef
# _log_cmd_example = ROT13 $@

define _cmd =
@$(if $(_log_cmd_$(1)), $(_log_before);printf '  %-9s %s\n' $(_log_cmd_$(1));$(_log_after);)
$(_cmd_$(1))
endef


## Add your built files to the CLEANUP_FILES variable to have them
## cleaned up by the clean goal.

define _cmd_clean =
$(Q)rm -rf -- $(CLEANUP_FILES)
endef
_log_cmd_clean = CLEAN

.PHONY: clean
clean:
	$(call _cmd,clean)


## Set the ARCHIVE_PREFIX variable to specify the path prefix used for
## the contents of all created tar archives.

# Set a default so that using COMPILED_ARCHIVE works correctly without
# specifying an ARCHIVE_PREFIX
ARCHIVE_PREFIX ?= ./

# Remove leading and add one trailing slash
_archive_prefix := $(patsubst %/,%,$(patsubst /%,%,$(ARCHIVE_PREFIX)))/

# Check if we have a git binary. The _git variable should only be used
# when _git is known to be non-empty. If git is required when it is
# not available, an error should be raised.
GIT ?= git
_git = $(shell command -v $(GIT))

_git_working_copy_clean = $(_git) diff-index --quiet HEAD

# Check if we have a curl binary, same as for _git.
CURL ?= curl
_curl = $(shell command -v $(CURL))


######################################################################
### Git source archive
######################################################################

## Set the SOURCE_ARCHIVE variable to a file name to create a rule
## which will create a git archive with that name for the head
## revision. The archive will also include submodules.
##
## The SOURCE_ARCHIVE_PATH variable can be used to specify what is to
## be included in the source archive. The path is relative to the root
## of the git working copy. The default includes everything.
##
## The ARCHIVE_PREFIX variable will specify the prefix path for the
## archive.

ifneq ($(SOURCE_ARCHIVE),)

CLEANUP_FILES += $(SOURCE_ARCHIVE)

SOURCE_ARCHIVE_PATH ?= .

ifeq ($(_git),)
$(SOURCE_ARCHIVE):
	$(error Git does not appear to be installed)
else
# The git ref file indicating the age of HEAD
GIT_HEAD_REF := $(shell $(_git) rev-parse --symbolic-full-name HEAD)
GIT_TOP_DIR := $(shell $(_git) rev-parse --show-toplevel)
GIT_HEAD_REF_FILE := $(shell $(_git) rev-parse --git-path $(GIT_HEAD_REF))

# Handle that older git versions output git-path results relative to
# the git top dir instead of relative to cwd
GIT_HEAD_REF_FILE := $(shell if [ -f $(GIT_HEAD_REF_FILE) ]; then \
                               echo $(GIT_HEAD_REF_FILE); \
                             else \
                               echo $(GIT_TOP_DIR)/$(GIT_HEAD_REF_FILE); \
                             fi)

# Note that we archive the commit tree object HEAD^{tree} rather than
# the commit object HEAD. The reason for this is to circumvent a
# problem with podman/buildah which will currently error out if it
# finds a global extended header when adding a tar archive.
#
# The git archive command will generate tar archives with a global
# extended header containing the commit hash as a comment if the
# archived object is a commit.
define _cmd_source_archive =
$(Q)if ! $(_git_working_copy_clean); then \
  echo >&2 "*** NOTE - These uncommitted changes aren't included in $@: ***"; \
  $(_git) status --short; \
fi; \
set -u && \
tmpdir=$$(pwd)/$$(mktemp -d submodules.XXXXX) && \
trap "rm -rf -- \"$$tmpdir\"" EXIT INT TERM && \
(cd "$(GIT_TOP_DIR)" && \
  $(_git) archive \
    -o "$(CURDIR)/$@" \
    --prefix="$(_archive_prefix)" \
    HEAD^{tree} $(SOURCE_ARCHIVE_PATH) && \
  $(_git) submodule sync && \
  $(_git) submodule update --init && \
  $(_git) submodule --quiet foreach 'echo $$path' | while read path; do \
    match=$$(find $(SOURCE_ARCHIVE_PATH) -samefile $$path); \
    if [ -n "$$match" ]; then \
      (cd "$$path" && \
      $(_git) archive \
	-o "$$tmpdir/submodule.tar" \
	--prefix="$(_archive_prefix)$$path/" \
	HEAD^{tree} . && \
      tar --concatenate -f "$(CURDIR)/$@" "$$tmpdir/submodule.tar"); \
    fi \
  done) && \
rm -rf -- "$$tmpdir"
endef
_log_cmd_source_archive = SOURCE $@

$(SOURCE_ARCHIVE): $(GIT_HEAD_REF_FILE)
	$(call _cmd,source_archive)

endif # ifeq ($(_git),)
endif # ifneq ($(SOURCE_ARCHIVE),)


######################################################################
### Node packages
######################################################################

## Use the variable $(NODE_MODULES) as a prerequisite to ensure node
## modules are installed for a make rule. Node modules will be
## installed with yarn if it is available, otherwise with npm.
##
## Set the variable PACKAGE_JSON, if the package.json file is not in
## the top-level directory.

NODE = node
PACKAGE_JSON ?= package.json
NODE_MODULES ?= $(dir $(PACKAGE_JSON))node_modules/.mark

$(NODE_MODULES): $(PACKAGE_JSON)
	$(Q)(cd $(dir $<) && \
	if command -v yarn >/dev/null; then \
	  yarn; \
	elif command -v npm >/dev/null; then \
	  npm install; \
	else \
	  echo >&2 "Neither yarn nor npm is available"; \
	  exit 1; \
	fi; \
	) && touch $@



######################################################################
### Compiled archive from source archive
######################################################################

## Set the COMPILED_ARCHIVE variable to a file name to create a rule
## which will run the shell command specified by COMPILE_COMMAND in a
## temporary directory where the SOURCE_ARCHIVE has been unpacked. The
## directory will be packed again into COMPILED_ARCHIVE.
##
## The ARCHIVE_PREFIX variable will specify the prefix path for the
## archive.

ifneq ($(COMPILED_ARCHIVE),)

CLEANUP_FILES += $(COMPILED_ARCHIVE)

define _cmd_compile_archive =
$(Q)set -u && \
tmpdir=$$(pwd)/$$(mktemp -d compilation.XXXXX) && \
trap "rm -rf -- \"$$tmpdir\"" EXIT INT TERM && \
(tar -C "$$tmpdir" -xf $(SOURCE_ARCHIVE) && \
  (cd "$$tmpdir"/$(_archive_prefix) && $(COMPILE_COMMAND)) && \
  tar -C "$$tmpdir" -cf $(COMPILED_ARCHIVE) $(_archive_prefix))
rm -rf -- "$$tmpdir"
endef
_log_cmd_compile_archive = COMPILE $(COMPILED_ARCHIVE)

$(COMPILED_ARCHIVE): $(SOURCE_ARCHIVE)
	$(call _cmd,compile_archive)

endif


######################################################################
### Container image
######################################################################

## Set the IMAGE_REPO variable to a container registry URL to create
## rules which will build and push a container image.
##
## The IMAGE_REPO variable and optionally the IMAGE_TAG_PREFIX
## variable specify how the image should be tagged. GitLab CI
## variables also affect the tag.
##
## IMAGE_REPO currently needs to be a docker URL without the preceding
## "docker://" transport.
##
## The IMAGE_REGISTRY and CI_REGISTRY variables will override the
## registry in IMAGE_REPO.
##
## Set the IMAGE_ARCHIVE variable to create rules for building and
## saving the container image to a tar archive.
##
## Set IMAGE_DOCKERFILE to specify a non-default dockerfile path. The
## default is Dockerfile in the current directory.
##
## If the container image uses any built file, these should be added
## to the IMAGE_FILES variable.
##
## Set IMAGE_BUILD_VOLUME to an absolute path to a directory to make
## it available in the container during the build phase.
##
## The contents of this directory should be added to the IMAGE_FILES
## variable to ensure it is tracked properly.  This can be used to
## ship in binary packages or resources that are only used for
## installation inside the container.
##
## The build-publish goal will build an image, optionally run a test,
## and push the image.
##
## If the variable IMAGE_TEST_CMD is set, the image will be run as a
## container with the variables contents as the command. If this
## returns a non-zero exit status the goal will fail, and the image
## will not be pushed.
##
## Additional arguments to running the test container may be passed
## with IMAGE_TEST_ARGS. Often this needs to contain "-t".
##
## The test may also be run separately with the test-image goal.
##
## The build and save goals both build an image and export it to
## $(IMAGE_ARCHIVE).
##
## The load goal loads $(IMAGE_ARCHIVE) into the container storage.
## This is used for local testing of containers. The
## remove-local-image goal will remove the image again.
##
## The run-image goal expects the image to be loaded. It will run the
## image using the optional IMAGE_RUN_ARGS and IMAGE_RUN_CMD.
##
## The publish goal expects the $(IMAGE_ARCHIVE) to exist and will
## load it into the container storage. It will re-tag it to the final
## tag and push the image.
##
## The login goal will login to the registry server of IMAGE_REPO. It
## will use GitLab CI credentials from the environment if the CI
## variable is set, otherwise credentials will be prompted for if
## necessary.
##
## PODMAN_PULL can be set to an argument like "--pull-never" in order
## to not pull a fresh upstream container, like in cases where a
## previous local container in a CI step is to be used.
##
## PODMAN_RUNTIME controls which runtime to use, crun, runc, other.
## This can be required to change depending on the host OS and how it
## uses cgroups.
## (cgroup v2 is at the moment only supported on crun, not runc)

define _cmd_image =
@$(if $(_log_cmd_image_$(1)), $(_log_before);printf '  %-9s %s\n' $(_log_cmd_image_$(1));$(_log_after);)
$(Q)if command -v podman >/dev/null >/dev/null; then \
  $(_cmd_image_podman_$(1)); \
elif command -v docker >/dev/null; then \
  $(_cmd_image_docker_$(1)); \
else \
  echo >&2 "Neither podman nor docker is available"; \
  exit 1; \
fi
endef

ifneq ($(IMAGE_REPO),)

.PHONY: build save load run-image remove-local-image publish build-publish login temp-publish temp-pull

IMAGE_DOCKERFILE ?= Dockerfile
IMAGE_ARCHIVE ?= dummy.tar

CLEANUP_FILES += $(IMAGE_ARCHIVE)

ifeq ($(_git),)
build-publish $(IMAGE_ARCHIVE) build save publish:
	$(error Git does not appear to be installed, images cannot be tagged)
else

# The branch or tag name for which project is built
CI_COMMIT_REF_NAME ?= $(shell $(_git) rev-parse --abbrev-ref HEAD)
CI_COMMIT_REF_NAME := $(subst /,_,$(CI_COMMIT_REF_NAME))
CI_COMMIT_REF_NAME := $(subst \#,_,$(CI_COMMIT_REF_NAME))

# The commit revision for which project is built
CI_COMMIT_SHA ?= $(shell git rev-parse HEAD)

# The unique id of the current pipeline that GitLab CI uses internally
CI_PIPELINE_ID ?= no-pipeline

# The unique id of runner being used
_host := $(shell uname -a)

# Build timestamp
_date := $(shell date +%FT%H:%M%z)

# URL
CI_PROJECT_URL ?= http://localhost.localdomain/

ifneq ($(IMAGE_TAG_PREFIX),)
_image_tag_prefix := $(patsubst %-,%,$(IMAGE_TAG_PREFIX))-
endif

IMAGE_TAG_SUFFIX ?= $(CI_COMMIT_REF_NAME)

# Unique for this build
IMAGE_LOCAL_TAG = $(_image_repo):$(_image_tag_prefix)$(CI_PIPELINE_ID)

# Final tag
IMAGE_TAG = $(_image_repo):$(_image_tag_prefix)$(IMAGE_TAG_SUFFIX)

_podman = podman


ifdef IMAGE_BUILD_FROM
_image_build_from_arg = --build-arg=IMAGE_BUILD_FROM="$(IMAGE_BUILD_FROM)"
else
_image_build_from_arg =
endif


ifdef IMAGE_BUILD_VOLUME
_build_volume = --volume $(IMAGE_BUILD_VOLUME):/build:ro,z
else
_build_volume =
endif


ifdef BUILDAH_RUNTIME
$(warning You should use PODMAN_RUNTIME instead of BUILDAH_RUNTIME)
endif

ifdef PODMAN_RUNTIME
_podman_run = $(_podman) --runtime=$(PODMAN_RUNTIME) run
else ifdef BUILDAH_RUNTIME
_podman_run = $(_podman) --runtime=$(BUILDAH_RUNTIME) run
else
_podman_run = $(_podman) run
endif



ifdef PODMAN_PULL
_podman_pull_args = $(PODMAN_PULL)
else
_podman_pull_args = --pull-always
endif

ifdef BUILDAH_PULL
$(error You should use PODMAN_PULL instead of BUILDAH_PULL)
endif


define _cmd_image_podman_build =
  $(_podman) build $(_podman_pull_args) \
    $(_build_volume) \
    --file=$< \
    --build-arg=BRANCH="$(CI_COMMIT_REF_NAME)" \
    --build-arg=COMMIT="$(CI_COMMIT_SHA)" \
    --build-arg=URL="$(CI_PROJECT_URL)" \
    --build-arg=DATE="$(_date)" \
    --build-arg=HOST="$(_host)" \
    $(_image_build_from_arg) \
    --tag=$(IMAGE_LOCAL_TAG) \
    .
endef
define _cmd_image_docker_build =
  docker build --pull --no-cache \
    --file=$< \
    $(_build_volume) \
    --build-arg=BRANCH="$(CI_COMMIT_REF_NAME)" \
    --build-arg=COMMIT="$(CI_COMMIT_SHA)" \
    --build-arg=URL="$(CI_PROJECT_URL)" \
    --build-arg=DATE="$(_date)" \
    --build-arg=HOST="$(_host)" \
    $(_image_build_from_arg) \
    --tag=$(IMAGE_LOCAL_TAG) \
    .
endef
_log_cmd_image_build = BUILD $(IMAGE_LOCAL_TAG)

define _cmd_image_podman_publish =
  $(_podman) push $(IMAGE_LOCAL_TAG) docker://$(IMAGE_TAG) && \
  $(_podman) rmi $(IMAGE_LOCAL_TAG)
endef
define _cmd_image_docker_publish =
  docker tag $(IMAGE_LOCAL_TAG) $(IMAGE_TAG) && \
  docker rmi $(IMAGE_LOCAL_TAG) && \
  docker push $(IMAGE_TAG) && \
  docker rmi $(IMAGE_TAG)
endef
_log_cmd_image_publish = PUBLISH $(IMAGE_TAG)


define _cmd_image_podman_temp-publish =
  $(_podman) push $(IMAGE_LOCAL_TAG) docker://$(IMAGE_LOCAL_TAG) && \
  $(_podman) rmi $(IMAGE_LOCAL_TAG)
endef
define _cmd_image_docker_temp-publish =
  docker push $(IMAGE_LOCAL_TAG) && \
  docker rmi $(IMAGE_LOCAL_TAG)
endef
_log_cmd_image_temp-publish = TEMP-PUBLISH $(IMAGE_LOCAL_TAG)


define _cmd_image_podman_save =
  $(_podman) push $(IMAGE_LOCAL_TAG) docker-archive:$(IMAGE_ARCHIVE):$(IMAGE_LOCAL_TAG) && \
  $(_podman) rmi $(IMAGE_LOCAL_TAG)
endef
define _cmd_image_docker_save =
  docker save $(IMAGE_LOCAL_TAG) > $(IMAGE_ARCHIVE) && \
  docker rmi $(IMAGE_LOCAL_TAG)
endef
_log_cmd_image_save = SAVE $(IMAGE_ARCHIVE)

build-publish: $(IMAGE_DOCKERFILE) $(IMAGE_FILES)
	$(call _cmd_image,build)
	$(call _cmd_image,test)
	$(call _cmd_image,publish)

######################################################################
### Testing the image
######################################################################

## When building complex applications, sometimes you want to run
## integration tests inside the image used for production.
##
## Simple tests can be done by setting the variable
## IMAGE_TEST_CMD in combination with IMAGE_TEST_ARGS as discussed in
## the "Container Image" section
##
## More complex tests, that require runtime services, like databases
## and more can be performed by using the temp-publish target.
##
## The temp-publish target will publish a container to the registry
## with a tag that is combined from the image tag prefix and the
## variable CI_PIPELINE_ID.
##
## Usually this comes in the form of
## registry.gitlab.com/myname/myproject/mycontainer:${CI_PIPELINE_ID}
##
## To use it, declare a CI step as depending on the one calling
## `make temp-publish` with the `image: ` argument set
## registry.gitlab.com/myname/myproject/container-name:${CI_PIPELINE_ID}
## and adding whatever container services you need.
##
## Then, the step after your integration test, call `make temp-pull`
## followed by `make publish`.
##
## An example here, in approximate .gitlab-ci.yml syntax
##
## build:
##   image: something/something
##   script:
##     - make temp-publish
##
## integration:
##   needs:
##     - build
##   image: registry.gitlab.com/myname/myproj/container:${CI_PIPELINE_ID}
##   services:
##     - postgres/latest
##   script:
##     - /usr/local/bin/testcase
##
## publish:
##   image: something/something
##   needs:
##     - integration
##     - build
##   script:
##     - make temp-pull
##     - make publish
##
##

temp-publish: $(IMAGE_DOCKERFILE) $(IMAGE_FILES)
	$(call _cmd_image,build)
	$(call _cmd_image,test)
	$(call _cmd_image,temp-publish)

# Save the existing image to a tar archive. Remove any existing
# archive first, because podman won't overwrite it.
$(IMAGE_ARCHIVE): $(IMAGE_DOCKERFILE) $(IMAGE_FILES)
	$(call _cmd_image,build)
	$(Q)rm -f -- $(IMAGE_ARCHIVE)
	$(call _cmd_image,save)

build save: $(IMAGE_ARCHIVE)

publish:
	$(call _cmd_image,load)
	$(call _cmd_image,publish)

endif # ifeq($(_git),)

define _cmd_image_podman_load =
  podman load < $(IMAGE_ARCHIVE)
endef
define _cmd_image_docker_load =
  docker load < $(IMAGE_ARCHIVE)
endef
_log_cmd_image_load = LOAD $(IMAGE_ARCHIVE)

load:
	$(call _cmd_image,load)


define _cmd_image_podman_temp-pull =
  $(_podman) pull docker://$(IMAGE_LOCAL_TAG)
endef
define _cmd_image_docker_temp-pull =
  docker pull $(IMAGE_LOCAL_TAG)
endef
_log_cmd_image_temp-pull = TEMP-PULL $(IMAGE_LOCAL_TAG)

temp-pull:
	$(call _cmd_image,temp-pull)
	$(call _cmd_image,save)

define _cmd_image_podman_run =
  $(_podman_run) --rm $(IMAGE_RUN_ARGS) $(IMAGE_LOCAL_TAG) $(IMAGE_RUN_CMD)
endef
define _cmd_image_docker_run =
  docker run --rm $(IMAGE_RUN_ARGS) $(IMAGE_LOCAL_TAG) $(IMAGE_RUN_CMD)
endef
_log_cmd_image_run = RUN $(IMAGE_LOCAL_TAG)

run-image:
	$(call _cmd_image,run)

IMAGE_TEST_ARGS ?= $(IMAGE_RUN_ARGS)
define _cmd_image_podman_test =
  $(if $(IMAGE_TEST_CMD),$(_podman_run) --rm $(IMAGE_TEST_ARGS) $(IMAGE_LOCAL_TAG) $(IMAGE_TEST_CMD),:)
endef
define _cmd_image_docker_test =
  $(if $(IMAGE_TEST_CMD),docker run --rm $(IMAGE_TEST_ARGS) $(IMAGE_LOCAL_TAG) $(IMAGE_TEST_CMD),:)
endef
_log_cmd_image_test = TEST $(IMAGE_LOCAL_TAG) $(if $(IMAGE_TEST_CMD),,"(skipped)")

test-image:
	$(call _cmd_image,test)

# Remove loaded image command, for the automated test
define _cmd_image_podman_rmi_local =
  podman rmi $(IMAGE_LOCAL_TAG)
endef
define _cmd_image_docker_rmi_local =
  docker rmi $(IMAGE_LOCAL_TAG)
endef
_log_cmd_image_rmi_local = RMI $(IMAGE_LOCAL_TAG)

remove-local-image:
	$(call _cmd_image,rmi_local)

endif # ifneq ($(IMAGE_REPO),)


ifneq ($(IMAGE_REPO)$(CI_REGISTRY)$(IMAGE_REGISTRY),)

# Handle IMAGE_REPO set to $(CI_REGISTRY)/... when CI_REGISTRY is unset
_image_repo_fixup = $(patsubst /%,localhost/%,$(IMAGE_REPO))

_image_repo_registry = $(firstword $(subst /, ,$(_image_repo_fixup)))

ifeq ($(IMAGE_REGISTRY),)
ifneq ($(CI_REGISTRY),)
IMAGE_REGISTRY = $(CI_REGISTRY)
else
IMAGE_REGISTRY = $(_image_repo_registry)
endif # ifneq ($(CI_REGISTRY),)
endif # ifeq ($(IMAGE_REGISTRY),)

_image_repo = $(patsubst $(_image_repo_registry)/%,$(IMAGE_REGISTRY)/%,$(_image_repo_fixup))

ifneq ($(CI),)
ifeq ($(CI_REGISTRY),$(IMAGE_REGISTRY))
_registry_login_user = -u gitlab-ci-token
endif # ifeq ($(CI_REGISTRY),$(IMAGE_REGISTRY))
endif # ifneq ($(CI),)

define _cmd_image_podman_login =
  echo "$$CI_BUILD_TOKEN" | podman login $(_registry_login_user) --password-stdin $(IMAGE_REGISTRY)
endef
define _cmd_image_docker_login =
  echo "$$CI_BUILD_TOKEN" | docker login $(_registry_login_user) --password-stdin $(IMAGE_REGISTRY)
endef
_log_cmd_image_login = LOGIN $(IMAGE_REGISTRY)

login:
	$(call _cmd_image,login)

endif # ifneq ($(IMAGE_REPO)$(CI_REGISTRY)$(IMAGE_REGISTRY),)

######################################################################
### Test sequence helpers
######################################################################

## To run a series of tests where any may fail without stopping the
## make recipe, use $(RECORD_TEST_STATUS) after each command, and end
## the rule with $(RETURN_TEST_STATUS)

RECORD_TEST_STATUS = let "_result=_result|$$?";
RETURN_TEST_STATUS = ! let _result;


######################################################################
### Fedora root archive
######################################################################

## Set the FEDORA_ROOT_ARCHIVE variable to a file name to create a
## rule which will build a tar archive of a small Fedora root file
## system. The archive will be suitable for adding to a scratch
## container image.
##
## The FEDORA_ROOT_RELEASE variable specifies the Fedora release to
## use.
##
## The FEDORA_ROOT_PACKAGES variable should be set to a list of
## packages to be installed in the file system.
##
## The file system is built using dnf install --installroot, so the
## rule needs to be run with root privileges to work.

ifneq ($(FEDORA_ROOT_ARCHIVE),)

CLEANUP_FILES += $(FEDORA_ROOT_ARCHIVE)

ifeq ($(FEDORA_ROOT_RELEASE),)
  $(error You must set FEDORA_ROOT_RELEASE to build a Fedora root file system)
endif

define _cmd_fedora_root =
$(Q)set -u && \
tmpdir=$$(pwd)/$$(mktemp -d fedora_root.XXXXX) && \
trap "rm -rf -- \"$$tmpdir\"" EXIT INT TERM && \
dnf install \
  --installroot "$$tmpdir" \
  --releasever $(FEDORA_ROOT_RELEASE) \
  --disablerepo "*" \
  --enablerepo "fedora" \
  --enablerepo "updates" \
  $(FEDORA_ROOT_PACKAGES) \
  glibc-minimal-langpack \
  --setopt install_weak_deps=false \
  --assumeyes && \
rm -rf -- \
  "$$tmpdir"/var/cache \
  "$$tmpdir"/var/log/dnf* && \
tar -C "$$tmpdir" -cf $(CURDIR)/$@ . && \
rm -rf -- "$$tmpdir"
endef
_log_cmd_fedora_root = DNF $@

$(FEDORA_ROOT_ARCHIVE):
	$(call _cmd,fedora_root)

endif


######################################################################
### Update build.mk from GitLab
######################################################################

## Run `make update-build.mk` to make a git commit where this file is
## replaced with the version from master in the GitLab project.

# Use the web interface, since git archive --remote against GitLab
# does not appear to work.
_buildmk_baseurl = https://gitlab.com/ModioAB/build.mk
_buildmk_release_ref = master
_buildmk_repo = $(_buildmk_baseurl).git

define _cmd_update_buildmk =
$(Q)if ! $(_git_working_copy_clean); then \
  echo >&2 "The git working copy needs to be clean."; \
else \
  $(_git) ls-remote -q $(_buildmk_repo) $(_buildmk_release_ref) | \
    (read buildmk_commit rest; \
     buildmk_url=$(_buildmk_baseurl)/raw/$${buildmk_commit}/build.mk; \
     $(_curl) -o $(_buildmk_path) $${buildmk_url}; \
     if $(_git) diff-index --quiet HEAD; then \
       echo >&2 "No changes to build.mk."; \
     else \
       $(_git) add $(_buildmk_path); \
       printf \
         "Update build.mk to %s\n\nThis version of build.mk was fetched from:\n%s" \
         $${buildmk_commit} \
         $${buildmk_url} | \
       $(_git) commit -F -; \
     fi); \
fi
endef
_log_cmd_update_buildmk = UPDATE $(_buildmk_path)

.PHONY: update-build.mk
update-build.mk:
ifeq ($(_git),)
	$(error Git does not appear to be installed)
else ifeq ($(_curl),)
	$(error Curl does not appear to be installed)
else
	$(call _cmd,update_buildmk)
endif # ifeq ($(_git),)
