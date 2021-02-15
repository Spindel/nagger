# Merge Nagger

A small Merge request nagger and some tooling that came from that

## CI usage, nag mode

1. Invite "Naggus Bottus" into your project as _reporter_
2. Create an API token for Naggus Bottus to use, and add it to the project
   under the variable name "NAGGUS_KEY"

3. Add a CI step like this:

```yaml
image: registry.gitlab.com/modioab/naggus:master
script:
- nagger nag
```

`nagger` will run on each commit, using the permissions in the NAGGUS_KEY
token, and will ensure that if there is an Merge Request open, it has a
Milestone, and comment on that.


## CI Usage, Release mode

1. Invite "Naggus Bottus" into your project as a _developer_ 
2. Create an API token for Naggus Bottus to use, and add it to the project
   under the variable name "NAGGUS_KEY"
3. Add a CI step like this:

```yaml
image: registry.gitlab.com/modioab/naggus:master
only:
- tags
script:
- nagger release
```


# Manual usage cases

## Prepare Changelog

1. Create an API token for your usecase in the console
2. Install `nagger` (see below)  by doing `pip install .`  In the command line, 

## Tag a release


When ran from a CI pipeline, the following commands are applicable
$ nagger make-release



# Installing nagger

Naggus bottus isn't on pypi right now, so you get to install it by doing:

```shell
virtualenv -p python3 /tmp/venv
source /tmp/venv/bin/activate

git clone https://gitlab.com/ModioAB/nagger.git
cd nagger
pip install .
```

# Using nagger

Nagger takes all it's configuration from the environment, because it's designed
to run in a CI system.

You can call it like this:
```shell
CI_API_V4_URL=https://gitlab.com/  NAGGUS_KEY=XXXXXx-XxXyyyyy nagger changelog v3.14 

```

## TODO and Notes

* Help texts are fairly minimal and could be more helpful
* All code shouldn't live in `__init__.py`
* Logging could take a configuration option too
* Documentation could probably be more helpful
* Hardcoded projects should probably not be hardcoded
* Tooling to migrate a milestone into the future and more?


# Features we don't have but want


## Open next milestone

1. Creates milestone v3
2. ~~Moves all open issues and merge requests from v2 to v3~~ 

## Tag a release

### Signed release tag 

Requires us to check out the code, sign it client side and push it manually,
which is out of scope for naggus

A cool thing would be to build a web service that uses u2f keys to keep gpg
keys in, and then only use it to create merges and tags against gitlab.

But that's for later.

Hard to do since we want to use signed git tags.  Could be done by doing a
standardized target "make TAG=v3.4.5 tag"  in each repo which could then do the
right thing (tm)

### Untagged releases


Otherwise it should:

0. Be configured with a list of projects to always tag
1. Get a release milestone
2. Build change-log from all Merged MR's this milestone
3. Build a list over all projects that were involved in this milestone
4. Iterate over projects, create a tag for each project
5. Iterate over projects, create a release for each project




