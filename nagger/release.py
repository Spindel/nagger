#!/usr/bin/env python3
"""Simple CI helper to remind people to set milestones"""
import io

from enum import IntEnum
from dataclasses import dataclass

from datetime import timezone

from dateutil.parser import isoparse

from structlog import get_logger
from structlog.contextvars import bind_contextvars, unbind_contextvars

from . import get_gitlab
from . import GROUP_NAME, RELEASE_PROJECTS, IGNORE_MR_PROJECTS

_log = get_logger("nagger")

DEBUG = False


class Kind(IntEnum):
    """What kind of changelog item is this?"""

    Feature = 0
    Bug = 1
    misc = 9


class Exposed(IntEnum):
    """Should this thing be visible to the outside or not."""

    External = 0
    Internal = 1


@dataclass(order=True)
class ChangeLog:
    """Tracking a changelog line"""

    kind: Kind
    exposed: Exposed
    text: str
    slug: str


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


def get_milestone(gl, milestone_name):
    bind_contextvars(milestone_name=milestone_name, group_name=GROUP_NAME)
    group = gl.groups.get(GROUP_NAME)
    ms = group.milestones.list()
    our_ms = (m for m in ms if m.state == "active" and m.title == milestone_name)
    milestone = next(our_ms)
    bind_contextvars(milestone_iid=milestone.iid)
    return milestone


def is_version(name):
    """Try to see if a name is a version number."""
    ALL_NUM = set("0123456789.")
    if name[0] in ("v", "V"):
        part = name[1:]
    else:
        part = name
    return ALL_NUM > set(part)


def test_is_version():
    """Test for what we want to be versions."""
    assert is_version("v1.23.2") is True
    assert is_version("V1.23") is True
    assert is_version("V123") is True
    assert is_version("12.33") is True
    assert is_version("autumn") is False
    assert is_version("Version 2") is False
    assert is_version("v 2.33") is False
    assert is_version("v%2.33") is False
    assert is_version("2020-03-21") is False


def get_milestones():
    """Gets a list of active milestones."""
    gl = get_gitlab()
    bind_contextvars(group_name=GROUP_NAME)
    group = gl.groups.get(GROUP_NAME)
    _log.debug("Retrieving milestones")
    active_milestones = group.milestones.list(state="active")
    filtered = (m for m in active_milestones if is_version(m.title))
    result = [m.title for m in filtered]
    return result


def projects_from_mrs(gl, merge_requests):
    """Look up projects from merge requests"""
    projects = {}

    for mr in merge_requests:
        if mr.project_id in projects:
            continue
        _log.info("Looking up project", project_id=mr.project_id)
        project = gl.projects.get(mr.project_id)
        projects[mr.project_id] = project
    return projects


def projects_from_list(api):
    """Iterate over our hard-coded projects, returning project ojbects"""
    projects = {}
    # Fill up with our "ALWAYS CREATE PROJECT"
    for name in RELEASE_PROJECTS:
        _log.info("Looking up project", project=name)
        proj = api.projects.get(name)
        projects[proj.id] = proj
    return projects


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


def milestone_changelog(milestone_name):
    """Stomps all over a milestone"""

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
    for project_id, merge_requests in changes.items():
        bind_contextvars(project_id=project_id, num_mrs=len(merge_requests))
        changelog = make_changelog(merge_requests)
        project = projects[project_id]
        proj_name = project.path_with_namespace
        external[proj_name] = [l for l in changelog if l.exposed == Exposed.External]
        internal[proj_name] = [l for l in changelog]
    unbind_contextvars("project_id", "num_mrs")
    del projects, changes, project, changelog

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
            result.write(f"* {c.kind.name}: {c.text}\n")
        result.write("\n")
    # End internal changes

    print("# Internal only changes\n")
    print(result.getvalue())


def milestone_fixup(milestone_name, pretend=False):
    """Stomps all over a milestone"""
    assert milestone_name, "Parameter missing: Milestone name"
    gl = get_gitlab()

    milestone = get_milestone(gl, milestone_name)
    assert milestone.start_date, "Milestone needs to have a Start date set"
    start_date = isoparse(milestone.start_date)
    # It's just a date and not a time, but other timestamps are datetimes
    # so we make it utc so they can be compared.
    start_date = start_date.replace(tzinfo=timezone.utc)

    # We don't use the milestone to get the merge requests, as we are
    # interested in all the ones NOT part of the milestone
    group = gl.groups.get(GROUP_NAME)

    # Grab all merge requests
    mrs = group.mergerequests.list(state="merged")

    # mapping of project_id => project object
    projects = projects_from_mrs(gl, mrs)
    for proj_id, proj in projects_from_list(gl).items():
        projects[proj_id] = proj

    # Maybe use dateutil.parse?

    for project in projects.values():
        bind_contextvars(project=project.path)
        if project.path_with_namespace in IGNORE_MR_PROJECTS:
            _log.msg("Ignoring")
            continue

        mrs = project.mergerequests.list(state="merged", order_by="created_at")
        mrs = (m for m in mrs if not m.milestone)

        for mr in mrs:
            merged_at = isoparse(mr.merged_at)
            if merged_at > start_date:
                bind_contextvars(mr_title=mr.title, mr_url=mr.web_url)
                mr.milestone_id = milestone.iid
                if not pretend:
                    try:
                        mr.save()
                    except Exception as e:
                        err = str(e)
                        _log.error("Failed to update", exception=err)
                unbind_contextvars("mr_title", "mr_url")
        unbind_contextvars("project")


def milestone_release(tag_name, dry_run):
    """Run manually to create a release in all projects"""
    assert tag_name.count(".") >= 2, "Tag should be a full version, v3.14.0"
    gl = get_gitlab()
    bind_contextvars(tag_name=tag_name)

    milestone_name = tag_name.rsplit(".", 1)[0]
    milestone = get_milestone(gl, milestone_name)
    mrs = milestone.merge_requests()
    merged_mrs = [m for m in mrs if m.state == "merged"]

    projects = projects_from_mrs(gl, merged_mrs)
    # Fill up with our "ALWAYS CREATE PROJECT"
    for name in RELEASE_PROJECTS:
        _log.info("Looking up id for", project=name)
        proj = gl.projects.get(name)
        projects[proj.id] = proj
    del name, proj

    changes = {}
    for project_id in projects:
        changes.setdefault(project_id, [])
    del project_id

    for mr in merged_mrs:
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
        bind_contextvars(project=project.path_with_namespace, project_id=project.id)
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
        bind_contextvars(**tag_prefs)
        if not dry_run:
            try:
                tag = project.tags.create(tag_prefs)
                _log.info("Created tag", commit=tag.id)
                print(f"{proj_name}:  tag: {tag_name} commit: {tag.id}")
            except Exception as e:
                err_msg = f"{e.__class__.__name__}: {e}"
                if DEBUG:
                    _log.exception("Error creating tag.")
                else:
                    _log.error("Error creating tag.", error=err_msg)

        release_prefs = {
            "tag_name": tag_name,
            "name": tag_name,
            "description": release_message,
            # We cannot link to Group Milestones by name, thus we pass an empty
            # milestone in here.  It should be the text representation of a
            # milestone name according to the documentation that is wrong.
            "milestones": [],
        }
        bind_contextvars(**release_prefs)
        if not dry_run:
            try:
                release = project.releases.create(release_prefs)
                _log.info("Created release", **release_prefs)
                print(f"{proj_name}:  tag: {release.tag_name}, release: {release.name}")
            except Exception as e:
                err_msg = f"{e.__class__.__name__}: {e}"
                if DEBUG:
                    _log.exception("Error creating release.")
                else:
                    _log.error("Error creating release.", exception=err_msg)
        unbind_contextvars(*release_prefs)
        unbind_contextvars(*tag_prefs)
    unbind_contextvars("project", "project_id")
