#!/usr/bin/env python3
"""Simple CI helper to remind people to set milestones"""
import os
import io
import sys

import structlog

from enum import IntEnum
from dataclasses import dataclass

_log = None

GROUP_NAME = "ModioAB"
IGNORE_MR_PROJECTS = ["ModioAB/sysadmin", "ModioAB/clientconfig"]


class Kind(IntEnum):
    Feature = 0
    Bug = 1
    misc = 9


class Exposed(IntEnum):
    External = 0
    Internal = 1


@dataclass(order=True)
class ChangeLog:
    """Tracking a changelog line"""

    kind: Kind
    exposed: Exposed
    text: str
    slug: str


def setup_logging():
    """Global state. Eat it"""
    import logging

    logging.basicConfig()
    global _log

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
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
    _log = _log.bind(API_URL=result)
    return result


def get_api_token():
    """Gets a api token from CI variables"""
    val = os.environ.get("NAGGUS_KEY")
    assert val, "Environment variable: NAGGUS_KEY is missing"
    return val.strip()


def get_mr_iid(api):
    """Gets a merge request id from CI variables"""
    global _log
    val = os.environ.get("CI_MERGE_REQUEST_IID")
    assert val, "Environment variable: CI_MERGE_REQUEST_IID missing"
    _log = _log.bind(CI_MERGE_REQUEST_IID=val)
    return val


def get_project_id():
    """Gets a project id from CI variables"""
    global _log
    val = os.environ.get("CI_PROJECT_ID")
    assert val, "Environment variable: CI_PROJECT_ID missing"
    val = int(val)
    _log = _log.bind(CI_PROJECT_ID=val)
    return val


def get_commit_tag():
    """Gets commit tag"""
    global _log
    val = os.environ.get("CI_COMMIT_TAG")
    assert val, "Environment variable: CI_COMMIT_TAG missing"
    _log = _log.bind(CI_COMMIT_TAG=val)
    return val


def get_commit_sha():
    """Gets commit tag"""
    global _log
    val = os.environ.get("CI_COMMIT_SHA")
    assert val, "Environment variable: CI_COMMIT_SHA missing"
    _log = _log.bind(CI_COMMIT_SHA=val)
    return val


def get_gitlab():
    """Create a gitlab instance from CI variables"""
    from gitlab import Gitlab

    global _log
    api_token = get_api_token()
    api_url = get_api_url()
    gl = Gitlab(api_url, api_token)
    # Authenticate so we can get our .user. data
    gl.auth()
    _log = _log.bind(API_USER=gl.user.username)
    return gl


def remove_own_emoji(thing, user_id, emoji="house"):
    """Remove an emoji owned by user_id from thing"""
    global _log
    emojis = thing.awardemojis.list()
    my_emojis = (e for e in emojis if e.user["id"] == user_id)
    to_remove = [e for e in my_emojis if e.name == emoji]
    for e in to_remove:
        _log.bind(emoji_removed=emoji)
        e.delete()
    return bool(to_remove)


def add_own_emoji(thing, user_id, emoji="house"):
    """Remove an emoji owned by user_id from thing"""
    global _log
    emojis = thing.awardemojis.list()
    my_emojis = (e for e in emojis if e.user["id"] == user_id)
    matching = [e for e in my_emojis if e.name == emoji]
    if not matching:
        _log.bind(emoji_added=emoji)
        thing.awardemojis.create({"name": emoji})


def debug_variables():
    """Print all CI related variables"""
    ci_keys = (k for k in os.environ if k.startswith("CI"))
    for key in sorted(ci_keys):
        val = os.environ[key]
        print(f"{key}={val}")


def make_pending(thing):
    """Make sure thing is not Ready, but is Pending"""
    global _log
    labels = set(thing.labels)
    try:
        labels.remove("Ready")
        _log = _log.bind(removed_label="Ready")
    except KeyError:
        pass
    labels.add("Pending")
    _log = _log.bind(added_label="Pending")
    try:
        thing.labels = list(labels)
        thing.save()
    except Exception:
        _log.exception("Error saving labels, permission error?")


def make_wip(thing):
    """Mark thing as WIP"""
    global _log
    if thing.work_in_progress:
        return

    old_title = thing.title
    thing.title = f"WIP: {old_title}"
    try:
        thing.save()
        _log = _log.bind(title=thing.title)
    except Exception:
        _log.exception("Error saving title, permission error?")


def nag_this_mr(api, mr):
    """Nag on a single mr"""
    global _log
    user_id = api.user.id
    project = api.projects.get(mr.project_id)

    author = mr.author["username"]
    _log = _log.bind(project=project.path_with_namespace)
    _log = _log.bind(mr_title=mr.title, author=author, nagger_user_id=user_id)

    bad_note = (
        f"Hello @{author}.\n\n"
        "You forgot to add a Milestone to this Merge Request.\n\n"
        "I will try to mark it as `Pending` and `WIP` "
        "so you do not forget to add a Milestone.\n\n"
        "Please, make sure the title is descriptive."
    )
    ok_note = (
        f"Hello @{author}.\n\n"
        "~~You forgot to add a Milestone to this Merge Request.~~\n\n"
        "~~I will try to mark it as `Pending` and `WIP` "
        "so you do not forget to add a Milestone.~~\n\n"
        "Please, make sure the title is descriptive."
    )

    if mr.milestone is None:
        _log = _log.bind(missing_milestone=True, commented=False)
        remove_own_emoji(mr, user_id=user_id, emoji="house")
        add_own_emoji(mr, user_id=user_id, emoji="house_abandoned")
        own_notes = [n for n in mr.notes.list() if n.author["id"] == user_id]
        if not own_notes:
            mr.notes.create({"body": bad_note})
            _log = _log.bind(commented=True)

        # in case we have an old modification (save failed) we re-load from
        # server
        mr = project.mergerequests.get(mr.iid)
        if not mr.work_in_progress:
            make_wip(mr)

        # in case we have an old modification (save failed) we re-load from
        # server
        mr = project.mergerequests.get(mr.iid)
        if ("Ready" in mr.labels) or ("Pending" not in mr.labels):
            make_pending(mr)

        _log.msg("Updated MR due to missing Milestone")
    else:
        own_notes = [n for n in mr.notes.list() if n.author["id"] == user_id]
        if own_notes:
            # We keep the first note, but update it
            note = own_notes.pop()
            add_own_emoji(note, user_id=user_id, emoji="thumbsup")
            if note.body != ok_note:
                note.body = ok_note
                note.save()
        # Delete any extra notes
        for note in own_notes:
            _log.msg("Deleting extra note", note_id=note.id, note_body=note.body)
            note.delete()

        remove_own_emoji(mr, user_id=user_id, emoji="house_abandoned")
        add_own_emoji(mr, user_id=user_id, emoji="house")
        _log.msg("Removing ugly emoji due to having Milestone")


def mr_nag():
    """Merge request nagger. meant to be run in a CI job"""
    global _log
    gl = get_gitlab()

    proj_id = get_project_id()
    project = gl.projects.get(proj_id)
    _log = _log.bind(project=project.path_with_namespace)

    mrs = []
    try:
        mr_iid = get_mr_iid()
        mrs = [project.mergerequests.get(mr_iid)]
    except Exception:
        pass

    if not mrs:
        # We don't have a MR id, so we have to find one from our commit id.
        commit_id = get_commit_sha()
        commit = project.commits.get(commit_id)

        # unlike project.merge_requests() this returns a list of dicts
        all_mrs = commit.merge_requests()
        # Reduce to "open"
        open_mrs = (m for m in all_mrs if "open" in m["state"])
        # Reduce to mrs on our project
        this_mrs = (m["iid"] for m in open_mrs if m["project_id"] == project.id)
        mrs = [project.mergerequests.get(mr_id) for mr_id in this_mrs]

    for mr in mrs:
        nag_this_mr(gl, mr)


def present_kind(val: Kind):
    if val == Kind.Feature:
        return "New features"
    if val == Kind.Bug:
        return "Bug fixes"
    if val == Kind.misc:
        return "Misc changes"
    return "XXX: "


def get_kind(mr):
    """Returns a kind based on the labels"""
    if "Feature" in mr.labels:
        return Kind.Feature
    if "Bug" in mr.labels:
        return Kind.Bug
    return Kind.misc


def get_exposed(mr):
    """Returns the exposed state of a merge requests"""
    if "Internal" in mr.labels:
        return Exposed.Internal
    return Exposed.External


def milestone_changelog(*args):
    """Stomps all over a milestone"""
    global _log
    milestone_name = " ".join(args)
    assert milestone_name, "Parameter missing: Milestone name"
    _log = _log.bind(milestone_name=milestone_name, group_name=GROUP_NAME)

    gl = get_gitlab()

    milestone = get_milestone(gl, milestone_name)
    mrs = milestone.merge_requests()

    # mapping of project_id => project object
    projects = {}

    # mapping of project_id => [ChangeLog, ChangeLog, ...]
    changes = {}
    merged_mr = (m for m in mrs if m.state == "merged")
    for mr in merged_mr:
        if mr.project_id not in projects:
            _log.info("Looking up", project_id=mr.project_id)
            projects[mr.project_id] = gl.projects.get(mr.project_id)
        changes.setdefault(mr.project_id, [])
        changes[mr.project_id].append(mr)

    external = {}
    internal = {}
    for project in projects.values():
        changelog = make_changelog(changes[project.id])
        proj_name = project.path_with_namespace
        external[proj_name] = [l for l in changelog if l.exposed == Exposed.External]
        internal[proj_name] = [l for l in changelog]
    del projects, changes

    # Data structure is now:
    #  external["ModioAB/afase"] = [change, change....]
    #  internal["ModioAB/afase"] = [change, change....]

    # External changes are visually different from internal.
    result = io.StringIO()
    for proj_name, changes in external.items():
        if not changes:
            continue
        header = f"## {proj_name}\n"
        result.write(header + "\n")

        for kind in Kind:
            subheader = f"{present_kind(kind)}: \n"
            lines = (l for l in changes if l.kind == kind)
            rows = [f"* {row.text}\n" for row in lines]
            if rows:
                result.write(subheader)
                result.writelines(rows)
                result.write("\n")

        result.write("\n\n")

    # Done, print it out (or save, or something)
    print("--8<--" * 10 + "\n")
    print(result.getvalue())
    result.close()
    print("-->8--" * 10 + "\n")

    # Internal changes are more concise
    result = io.StringIO()
    for proj_name, changes in internal.items():
        if not changes:
            continue
        result.write(f"## {proj_name}\n\n")
        for c in changes:
            result.write(f"{c.kind.name}: {c.text}\n")
        result.write("\n")
    # End internal changes

    print("# Internal only changes\n")
    print(result.getvalue())


def milestone_fixup(*args):
    """Stomps all over a milestone"""
    from datetime import timezone
    from dateutil.parser import isoparse

    global _log
    milestone_name = " ".join(args)
    assert milestone_name, "Parameter missing: Milestone name"
    _log = _log.bind(milestone_name=milestone_name)
    gl = get_gitlab()
    group = gl.groups.get(GROUP_NAME)
    milestone = get_milestone(gl, milestone_name)

    assert milestone.start_date, "Milestone needs to have a Start date set"
    start_date = isoparse(milestone.start_date)
    # It's just a date, but other timestamps are datetimes, so we make it utc
    start_date = start_date.replace(tzinfo=timezone.utc)

    # Grab all merge requests
    mrs = group.mergerequests.list(state="merged")
    projects = {m.project_id for m in mrs}
    # Maybe use dateutil.parse?

    for proj_id in projects:
        project = gl.projects.get(proj_id)
        if project.path_with_namespace in IGNORE_MR_PROJECTS:
            continue

        mrs = project.mergerequests.list(state="merged", order_by="created_at")
        mrs = (m for m in mrs if not m.milestone)
        for mr in mrs:
            merged_at = isoparse(mr.merged_at)
            if merged_at > start_date:
                print(mr.web_url)


def get_milestone(gl, milestone_name):
    group = gl.groups.get(GROUP_NAME)
    ms = group.milestones.list()
    our_ms = (m for m in ms if m.state == "active" and m.title == milestone_name)
    milestone = next(our_ms)
    return milestone


def make_changelog(merge_requests):
    """Returns a list of ChangeLog items"""
    result = []
    for mr in merge_requests:
        kind = get_kind(mr)
        exposed = get_exposed(mr)
        line = ChangeLog(kind, exposed, mr.title, f"!{mr.iid}")
        result.append(line)
    if not result:
        line = ChangeLog(Kind.misc, Exposed.External, "No major changes", "")
        result.append(line)
    return sorted(result)


def release_tag(*args):
    """Run from "only: -tags"  to turn tags into releases. WIP WIP WIP"""
    assert not args
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


COMMANDS = {
    "nag": mr_nag,
    "release": release_tag,
    "debug_variables": debug_variables,
    "changelog": milestone_changelog,
    "fixup": milestone_fixup,
}


def helptext():
    """Prints a help text"""
    command = sys.argv[0]
    print(f"Usage: {command} [subcommand]")
    for k in COMMANDS:
        print("\t", k)
    print("\n")
    print("We expect NAGGUS_KEY  environment to contain an API key")


def get_cmd():
    """Returns a function callable from sys.argv"""
    global _log
    if len(sys.argv) < 2:
        raise CmdError

    try:
        cmd = sys.argv[1]
        command = COMMANDS[cmd]
    except (KeyError, IndexError):
        raise CmdError
    args = sys.argv[2:]
    _log.bind(command=cmd)
    return command, args


def main():
    """Main command"""
    setup_logging()
    global _log

    try:
        command, args = get_cmd()
    except CmdError:
        helptext()
        sys.exit(1)
    try:
        command(*args)
    except Exception:
        _log.exception("Error in command")
        sys.exit(1)


if __name__ == "__main__":
    main()
