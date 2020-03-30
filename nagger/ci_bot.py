#!/usr/bin/env python3
"""Simple CI helper to remind people to set milestones"""
import os

from structlog import get_logger
from structlog.contextvars import bind_contextvars

from . import get_gitlab


_log = get_logger(__name__)


def get_mr_iid():
    """Gets a merge request id from CI variables"""
    val = os.environ.get("CI_MERGE_REQUEST_IID")
    assert val, "Environment variable: CI_MERGE_REQUEST_IID missing"
    bind_contextvars(CI_MERGE_REQUEST_IID=val)
    return val


def get_mr_iid_from_commit(project):
    """Try to guess the MR IIID based on the commit sha."""
    commit_id = get_commit_sha()
    commit = project.commits.get(commit_id)

    # unlike project.merge_requests() this returns a list of dicts
    all_mrs = commit.merge_requests()

    # Reduce to "open"
    open_mrs = (m for m in all_mrs if "open" in m["state"])

    # Reduce to mrs on our project
    this_mrs = [m["iid"] for m in open_mrs if m["project_id"] == project.id]
    return this_mrs


def get_project_id():
    """Gets a project id from CI variables"""
    val = os.environ.get("CI_PROJECT_ID")
    assert val, "Environment variable: CI_PROJECT_ID missing"
    val = int(val)
    bind_contextvars(CI_PROJECT_ID=val)
    return val


def get_project(api):
    """Get the current project from CI variables"""
    proj_id = get_project_id()
    project = api.projects.get(proj_id)
    bind_contextvars(project=project.path_with_namespace)
    return project


def get_commit_tag():
    """Gets commit tag"""
    val = os.environ.get("CI_COMMIT_TAG")
    assert val, "Environment variable: CI_COMMIT_TAG missing"
    bind_contextvars(CI_COMMIT_TAG=val)
    return val


def get_commit_sha():
    """Gets commit tag"""
    val = os.environ.get("CI_COMMIT_SHA")
    assert val, "Environment variable: CI_COMMIT_SHA missing"
    bind_contextvars(CI_COMMIT_SHA=val)
    return val


def remove_own_emoji(thing, user_id, emoji="house"):
    """Remove an emoji owned by user_id from thing"""
    emojis = thing.awardemojis.list()
    my_emojis = (e for e in emojis if e.user["id"] == user_id)
    to_remove = [e for e in my_emojis if e.name == emoji]
    for e in to_remove:
        bind_contextvars(emoji_removed=emoji)
        e.delete()
    return bool(to_remove)


def add_own_emoji(thing, user_id, emoji="house"):
    """Remove an emoji owned by user_id from thing"""
    emojis = thing.awardemojis.list()
    my_emojis = (e for e in emojis if e.user["id"] == user_id)
    matching = [e for e in my_emojis if e.name == emoji]
    if not matching:
        bind_contextvars(emoji_added=emoji)
        thing.awardemojis.create({"name": emoji})


def fun_debug_variables():
    """Print all CI related variables"""
    ci_keys = (k for k in os.environ if k.startswith("CI"))
    for key in sorted(ci_keys):
        val = os.environ[key]
        print(f"{key}={val}")


def make_pending(thing):
    """Make sure thing is not Ready, but is Pending"""
    labels = set(thing.labels)
    try:
        labels.remove("Ready")
        bind_contextvars(removed_label="Ready")
    except KeyError:
        pass
    labels.add("Pending")
    bind_contextvars(added_label="Pending")
    try:
        thing.labels = list(labels)
        thing.save()
    except Exception:
        _log.exception("Error saving labels, permission error?")


def make_wip(thing):
    """Mark thing as WIP"""
    if thing.work_in_progress:
        return

    old_title = thing.title
    thing.title = f"WIP: {old_title}"
    bind_contextvars(title=thing.title)
    try:
        thing.save()
    except Exception:
        _log.exception("Error saving title, permission error?")


def nag_this_mr(api, mr):
    """Nag on a single mr"""
    user_id = api.user.id
    project = api.projects.get(mr.project_id)

    author = mr.author["username"]
    bind_contextvars(
        project=project.path_with_namespace,
        mr_title=mr.title,
        author=author,
        nagger_user_id=user_id,
    )

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
        bind_contextvars(missing_milestone=True, commented=False)
        remove_own_emoji(mr, user_id=user_id, emoji="house")
        add_own_emoji(mr, user_id=user_id, emoji="house_abandoned")
        own_notes = [n for n in mr.notes.list() if n.author["id"] == user_id]
        if not own_notes:
            mr.notes.create({"body": bad_note})
            bind_contextvars(commented=True)

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
    gl = get_gitlab()
    project = get_project(api=gl)

    mrs = []
    try:
        mr_iid = get_mr_iid()
        mrs = [project.mergerequests.get(mr_iid)]
    except Exception:
        pass

    if not mrs:
        this_mrs = get_mr_iid_from_commit(project)
        mrs = [project.mergerequests.get(mr_id) for mr_id in this_mrs]

    for mr in mrs:
        nag_this_mr(gl, mr)


def release_tag():
    """Run from "only: -tags"  to turn tags into releases. WIP WIP WIP"""
    gl = get_gitlab()
    project = get_project(api=gl)

    tagname = get_commit_tag()

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
