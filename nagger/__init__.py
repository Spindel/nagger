#!/usr/bin/env python3
"""Simple CI helper to remind people to set milestones"""
import os
import io
import sys
from typing import List

import structlog

from enum import IntEnum
from dataclasses import dataclass

_log = None

GROUP_NAME = "ModioAB"
DEFAULT_API_URL = "https://gitlab.com/"
IGNORE_MR_PROJECTS = ["ModioAB/sysadmin", "ModioAB/clientconfig"]
RELEASE_PROJECTS = [
    "ModioAB/afase",
    "ModioAB/mytemp-backend",
    "ModioAB/modio-api",
    "ModioAB/zabbix-containers",
    "ModioAB/submit",
]


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
    web_url: str
    labels: List[str]


def setup_logging():
    """Global state. Eat it"""
    import sys

    global _log
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))
    _log = structlog.get_logger()
    _log.debug("Logging, debug, initialized")
    _log.msg("log.msg initialized")


class CmdError(Exception):
    """Command not found error"""


def get_api_url():
    """Gets a api url from CI variables"""
    from urllib.parse import urlparse

    global _log
    val = os.environ.get("CI_API_V4_URL", DEFAULT_API_URL)
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


def projects_from_mrs(gl, merge_requests):
    """Look up projects from merge requests"""
    global _log
    projects = {}

    for mr in merge_requests:
        if mr.project_id in projects:
            continue
        _log.info("Looking up", project_id=mr.project_id)
        project = gl.projects.get(mr.project_id)
        projects[mr.project_id] = project
    return projects


def milestone_changelog(*args):
    external_md, internal_md, milestone_name = make_milestone_changelog(*args)

    # Done, print it out (or save, or something)
    print("--8<--" * 10 + "\n")
    print(external_md)
    print("-->8--" * 10 + "\n")

    print("# Internal only changes\n")
    print(internal_md)


def make_milestone_changelog(*args):
    """Stomps all over a milestone"""
    global _log
    milestone_name = " ".join(args)
    assert milestone_name, "Parameter missing: Milestone name"
    _log = _log.bind(milestone_name=milestone_name, group_name=GROUP_NAME)

    gl = get_gitlab()

    milestone = get_milestone(gl, milestone_name)
    mrs = milestone.merge_requests()
    merged_mr = [m for m in mrs if m.state == "merged"]

    # mapping of project_id => project object
    projects = projects_from_mrs(gl, merged_mr)
    # mapping of project_id => [ChangeLog, ChangeLog, ...]
    changes = {}

    for mr in merged_mr:
        changes.setdefault(mr.project_id, [])
        changes[mr.project_id].append(mr)

    external = {}
    internal = {}
    for project in projects.values():
        if project.id not in changes:
            continue
        merge_requests = changes[project.id]
        changelog = make_changelog(merge_requests)
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
            labels = " ".join([f'~"{l}"' for l in c.labels])
            result.write(f"* [{c.text}]({c.web_url}) {labels}  \n")
        result.write("\n")
    # End internal changes

    print("# Internal only changes\n")
    print(result.getvalue())

    ensure_agile_wiki_page(f"Release-notes-{milestone_name}", result.getvalue())


def ensure_agile_wiki_page(title, content):
    WIKI_PROJECT = "ModioAB/agile"
    global _log
    _log = _log.bind(wiki_project=WIKI_PROJECT, title=title)
    gl = get_gitlab()
    project = gl.projects.get(WIKI_PROJECT)
    wikis = project.wikis
    pages = wikis.list()
    # if we use sane titles the slug will match title?
    found_page = [p for p in pages if p.slug == title]
    if not found_page:
        _log.info("wikipage does not exists")
        wikis.create({"title": title, "content": content})
    elif len(found_page) == 1:
        _log.info("wikipage exists")
        page = wikis.get(found_page[0].slug)
        page.content = content
        page.save()
    else:
        _log.msg("Duplicate page title %. Ignoring agile_wiki_page", title)
        return


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

    # mapping of project_id => project object
    projects = projects_from_mrs(gl, mrs)
    # Maybe use dateutil.parse?

    for project in projects.values():
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
        line = ChangeLog(kind, exposed, mr.title, f"!{mr.iid}", mr.web_url, mr.labels)
        result.append(line)
    if not result:
        line = ChangeLog(Kind.misc, Exposed.External, "No major changes", "")
        result.append(line)
    return sorted(result)


def milestone_release(*args):
    """Run manually to create a release in all projects"""
    global _log
    tag_name = " ".join(args)
    assert tag_name, "Parameter missing: Tag version , ex 'v3.14.0'"
    assert tag_name.count(".") >= 2, "Tag should be a full version, v3.14.0"
    milestone_name = tag_name.rsplit(".", 1)[0]
    _log = _log.bind(
        tag_name=tag_name, milestone_name=milestone_name, group_name=GROUP_NAME
    )

    gl = get_gitlab()
    milestone = get_milestone(gl, milestone_name)
    mrs = milestone.merge_requests()
    merged_mrs = [m for m in mrs if m.state == "merged"]

    projects = projects_from_mrs(gl, merged_mrs)
    # Fill up with our "ALWAYS CREATE PROJECT"
    for name in RELEASE_PROJECTS:
        _log.info("Looking up", project=name)
        proj = gl.projects.get(name)
        projects[proj.id] = proj
    del name, proj

    changes = {}
    for mr in merged_mrs:
        changes.setdefault(mr.project_id, [])
        changes[mr.project_id].append(mr)
    del mr, merged_mrs

    def make_text(incoming, fobj, external=True):
        """Creates a text representation of a changelog"""
        if external:
            # Format external facing as markdown text with links to issues
            our_lines = [l for l in incoming if l.exposed == Exposed.External]
            fmt = "* [{text}]({url}) \n"
        else:
            # Git internal tags just get plain text format issues
            our_lines = [l for l in incoming]
            fmt = "* {url}: {text} \n"

        for kind in Kind:
            lines = [l for l in our_lines if l.kind == kind]
            if not lines:
                continue
            fobj.write("\n")
            fobj.write(f"## {present_kind(kind)}: \n")
            for line in lines:
                if line.slug:
                    url = f"{project.path_with_namespace}{line.slug}"
                else:
                    url = ""
                txt = fmt.format(text=line.text, url=url)
                fobj.write(txt)

    for project in projects.values():
        if project.path_with_namespace in IGNORE_MR_PROJECTS:
            continue
        _log = _log.bind(project=project.path_with_namespace, project_id=project.id)
        release = io.StringIO()
        tag = io.StringIO()
        tag.write(f"Release {tag_name}\n")
        release.write(f"Release {tag_name}\n")
        release.write("\n")
        release.write(f"Milestone: {milestone.web_url} \n\n")

        changelog = make_changelog(changes[project.id])

        make_text(changelog, tag, external=False)
        make_text(changelog, release, external=True)

        tag_message = tag.getvalue()
        release_message = release.getvalue()

        tag.close()
        release.close()
        del tag, release

        proj_name = project.path_with_namespace
        tag_prefs = {"tag_name": tag_name, "message": tag_message, "ref": "master"}
        _log = _log.bind(**tag_prefs)
        try:
            tag = project.tags.create(tag_prefs)
            _log.info("Created tag", commit=tag.id)
            print(f"{proj_name}:  tag: {tag_name} commit: {tag.id}")
        except Exception:
            _log.exception("Error creating tag.")

        release_prefs = {
            "tag_name": tag_name,
            "name": tag_name,
            "description": release_message,
            # We cannot link to Group Milestones by name, thus we pass an empty
            # milestone in here.  It should be the text representation of a
            # milestone name according to the documentation that is wrong.
            "milestones": [],
        }
        _log = _log.bind(**release_prefs)
        try:
            release = project.releases.create(release_prefs)
            _log.info("Created release", **release_prefs)
            print(f"{proj_name}:  tag: {release.tag_name}, release: {release.name}")
        except Exception:
            _log.exception("Error creating release.")


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
    "milestone_release": milestone_release,
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
