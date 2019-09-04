#!/usr/bin/env python3
"""Simple CI helper to remind people to set milestones"""
import os
import sys
import structlog
import gitlab

_log = structlog.get_logger()


class CmdError(Exception):
    """Command not found error"""


def get_api_url():
    """Gets a api url from CI variables"""
    from urllib.parse import urlparse

    global _log

    val = os.environ.get("CI_API_V4_URL")
    assert val, "Environment variable: CI_API_V4_URL missing"
    # CI_API_.. is a full path, we just need the scheme+domain.
    parsed_uri = urlparse(val)
    result = "{uri.scheme}://{uri.netloc}/".format(uri=parsed_uri)
    _log = _log.bind(api_url=result)
    return result


def get_api_token():
    """Gets a api token from CI variables"""
    val = os.environ.get("CI_JOB_TOKEN")
    assert val, "Environment variable: CI_JOB_TOKEN missing"
    return val


def get_mr_iid():
    """Gets a merge request id from CI variables"""
    global _log
    val = os.environ.get("CI_MERGE_REQUEST_IID")
    assert val, "Environment variable: CI_MERGE_REQUEST_IID missing"
    _log = _log.bind(merge_request_iid=val)
    return val


def get_project_id():
    """Gets a project id from CI variables"""
    global _log
    val = os.environ.get("CI_PROJECT_ID")
    assert val, "Environment variable: CI_PROJECT_ID missing"
    _log = _log.bind(project_id=val)
    return val


def get_commit_tag():
    """Gets commit tag"""
    global _log
    val = os.environ.get("CI_COMMIT_TAG")
    assert val, "Environment variable: CI_COMMIT_TAG missing"
    _log = _log.bind(tag=val)
    return val


def get_gitlab():
    """Create a gitlab instance from CI variables"""
    global _log
    api_token = get_api_token()
    api_url = get_api_url()
    gl = gitlab.Gitlab(api_url, api_token)
    # Authenticate so we can get our .user. data
    gl.auth()
    _log = _log.bind(user=gl.user.username)
    return gl


def remove_own_emoji(thing, user_id, emoji="house"):
    """Remove an emoji owned by user_id from thing"""
    emojis = thing.awardemojis.list()
    my_emojis = (e for e in emojis if e.user["id"] == user_id)
    to_remove = (e for e in my_emojis if e.name == emoji)
    for e in to_remove:
        e.delete()


def add_own_emoji(thing, user_id, emoji="house"):
    """Remove an emoji owned by user_id from thing"""
    emojis = thing.awardemojis.list()
    my_emojis = (e for e in emojis if e.user["id"] == user_id)
    matching = [e for e in my_emojis if e.name == emoji]
    if not matching:
        thing.awardemojis.create({"name": emoji})


def print_ci():
    ci_keys = (k for k in os.environ if k.startswith("CI"))
    for key in ci_keys:
        val = os.environ[key]
        print(f"{key}={val}")


def mr_nag():
    """Merge request nagger. meant to be run in a CI job"""
    global _log
    proj_id = get_project_id()
    mr_iid = get_mr_iid()

    gl = get_gitlab()
    project = gl.projects.get(proj_id)
    _log = _log.bind(project=project.path_with_namespace)

    mr = project.mergerequests.get(mr_iid)
    author = mr.author["username"]
    _log = _log.bind(mr_description=mr.description, author=author)

    note = (
        f"Hello @{author}.  "
        "You forgot to add a Milestone to this Merge Request.  \n"
        "I have taken the liberty to mark it as `Pending` and `WIP`"
        "so you do not forget to add a Milestone."
        "\n"
        "Please, make sure the title is descriptive."
    )

    _log = _log.bind(title=mr.title)
    if mr.milestone is None:
        old_title = mr.title
        labels = set(mr.labels)
        if "Ready" in labels:
            labels.remove("Ready")
        labels.add("Pending")
        mr.labels = list(labels)
        if not mr.title.startswith("WIP:"):
            mr.title = f"WIP: {old_title}"

        remove_own_emoji(mr, user_id=gl.user.id, emoji="house")
        add_own_emoji(mr, user_id=gl.user.id, emoji="house_abandoned")

        _log.msg("Updated MR because missing Milestone")
        mr.save()
        mr.notes.create({"body": note})
    else:
        _log.msg("Removing ugly emoji due to having Milestone")
        remove_own_emoji(mr, user_id=gl.user.id, emoji="house_abandoned")
        add_own_emoji(mr, user_id=gl.user.id, emoji="house")


def release_tag():
    """Merge request nagger. meant to be run in a CI job"""
    global _log
    proj_id = get_project_id()

    tagname = get_commit_tag()
    gl = get_gitlab()
    project = gl.projects.get(proj_id)
    _log = _log.bind(project=project.path_with_namespace)

    all_rels = project.releases.list()
    for l in all_rels:
        print(l)
        print(vars(l))

    try:
        release = project.releases.get(tagname)
    except Exception:
        # Releases.get(foo)  raises 403 if not found
        release = None
        pass

    if release:
        _log.msg("Release found, bailing")
        return

    tag = project.tags.get(tagname)
    assert tag, "Missing tag even though CI said it exists"
    if not tag.message:
        _log.msg("Error, no message for tag")
        return

    _log.msg("Tag , message", tag=vars(tag), msg=tag.message)
    message = tag.message.split("\n")
    header = message[0]
    description = "\n".join(message[1:])

    commit = project.commits.get(tagname)
    _log.msg("got commit", commit=vars(commit))

    #    commit = project.commits.get(ref_name=tagname)
    assert commit.id == tag.target, "Commit ID and tag target differ"

    mrs = commit.merge_requests()
    _log.msg("got mrs", mrs=mrs)

    project.releases.create(
        {"name": header, "tag_name": tagname, "description": description}
    )


COMMANDS = {"nag": mr_nag, "release": release_tag}


def helptext():
    """Prints a help text"""
    command = sys.argv[0]
    print(f"Usage: {command} [subcommand]")
    for k in COMMANDS:
        print(k)


def get_cmd():
    """Returns a function callable from sys.argv"""
    if len(sys.argv) != 2:
        raise CmdError

    try:
        cmd = sys.argv[1]
        command = COMMANDS[cmd]
    except (KeyError, IndexError):
        raise CmdError
    return command


def main():
    """Main command"""
    print_ci()
    try:
        command = get_cmd()
    except CmdError:
        helptext()
        sys.exit(1)
    command()


if __name__ == "__main__":
    main()
