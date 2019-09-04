#!/usr/bin/env python3
"""Simple CI helper to remind people to set milestones"""
import os
import sys
import gitlab


class CmdError(Exception):
    """Command not found error"""

    ...


def get_api_url():
    """Gets a api url from CI variables"""
    from urllib.parse import urlparse

    val = os.environ.get("CI_API_V4_URL")
    assert val, "Environment variable: CI_API_V4_URL missing"
    parsed_uri = urlparse(val)
    result = '{uri.scheme}://{uri.netloc}/'.format(uri=parsed_uri)
    print("Using", result)
    return result


def get_api_token():
    """Gets a api token from CI variables"""
    val = os.environ.get("CI_JOB_TOKEN")
    assert val, "Environment variable: CI_JOB_TOKEN missing"
    return val


def get_mr_id():
    """Gets a merge request id from CI variables"""
    val = os.environ.get("CI_MERGE_REQUEST_ID")
    assert val, "Environment variable: CI_MERGE_REQUEST_ID missing"
    print("Using", val)
    return val


def get_project_id():
    """Gets a project id from CI variables"""
    val = os.environ.get("CI_MERGE_REQUEST_PROJECT_ID")
    assert val, "Environment variable: CI_MERGE_REQUEST_PROJECT_ID missing"
    print("Using", val)
    return val


def get_gitlab():
    """Create a gitlab instance from CI variables"""
    api_token = get_api_token()
    api_url = get_api_url()
    gl = gitlab.Gitlab(api_url, api_token)
    return gl


def remove_own_emoji(thing, user_id, emoji="house"):
    """Remove an emoji owned by user_id from thing"""
    emojis = thing.awardemjois.list()
    my_emojis = (e for e in emojis if e.user["id"] == user_id)
    to_remove = (e for e in my_emojis if e.name == emoji)
    for e in to_remove:
        e.delete()


def mr_nag():
    """Merge request nagger. meant to be run in a CI job"""
    proj_id = get_project_id()
    mr_id = get_mr_id()

    gl = get_gitlab()
    project = gl.projects.get(proj_id)
    mr = project.mergerequests.get(mr_id)
    author = mr.author.username

    note = (
        f"Hello @{author}.  "
        "You forgot to add a Milestone to this Merge Request.  \n"
        "I have taken the liberty to mark it as `Pending` and `WIP`"
        "so you do not forget to add a Milestone."
        "\n"
        "Please, make sure the title is descriptive."
    )

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
        mr.awardemojis.create({"name": "house_abandoned"})

        mr.save()
        mr.notes.create({"body": note})
    else:
        remove_own_emoji(mr, user_id=gl.user.id, emoji="house_abandoned")
        mr.awardemojis.create({"name": "house"})


COMMANDS = {"nag": mr_nag}


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
    try:
        command = get_cmd()
    except CmdError:
        helptext()
        sys.exit(1)
    command()


if __name__ == "__main__":
    main()
