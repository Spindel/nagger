#!/usr/bin/env python3
"""Simple CI helper to remind people to set milestones"""
import io

from enum import IntEnum
from dataclasses import dataclass

from datetime import timezone

from dateutil.parser import isoparse

from structlog import get_logger
from .logs import log_state
from structlog.contextvars import bind_contextvars, unbind_contextvars

from jinja2 import Environment, PackageLoader

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
    ms = group.milestones.list(all=True)
    our_ms = (m for m in ms if m.state == "active" and m.title == milestone_name)
    milestone = next(our_ms)
    bind_contextvars(milestone_id=milestone.id)
    return milestone


def get_template(template_name: str):
    environment = Environment(
        loader=PackageLoader("nagger", "templates"),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["present_kind"] = present_kind
    environment.globals["Kind"] = Kind
    return environment.get_template(template_name)


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


def get_milestones(gl):
    """Gets a list of active milestones."""
    bind_contextvars(group_name=GROUP_NAME)
    group = gl.groups.get(GROUP_NAME)
    _log.debug("Retrieving milestones")
    active_milestones = group.milestones.list(state="active", all=True)
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
        _log.info("Looking up project", project_name=name)
        proj = api.projects.get(name)
        _log.msg("Done", project=proj.path_with_namespace)
        projects[proj.id] = proj
    return projects


def make_changelog(merge_requests):
    """Returns a list of ChangeLog items"""
    result = []
    for mr in merge_requests:
        kind = get_kind(mr)
        exposed = get_exposed(mr)
        slug = mr.references["full"]
        line = ChangeLog(kind, exposed, mr.title, f"{slug}")
        result.append(line)
    return sorted(result)


def milestone_changelog(gl, milestone_name):
    """Stomps all over a milestone"""
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
    external_md = get_template("external.md")
    print("--8<--" * 10 + "\n")
    for proj_name, changes in external.items():
        templated = external_md.render(project=proj_name, changes=changes)
        print(templated)
    print("-->8--" * 10 + "\n")

    # Internal changes are more concise
    print("# Internal only changes\n")
    internal_md = get_template("internal.md")
    for proj_name, changes in internal.items():
        templated = internal_md.render(project=proj_name, changes=changes)
        print(templated)
    # End internal changes


def milestone_fixup(gl, milestone_name, pretend=False):
    """Stomps all over a milestone"""
    assert milestone_name, "Parameter missing: Milestone name"
    bind_contextvars(pretend=pretend)

    milestone = get_milestone(gl, milestone_name)
    assert milestone.start_date, "Milestone needs to have a Start date set"
    start_date = isoparse(milestone.start_date)
    # It's just a date and not a time, but other timestamps are datetimes
    # so we make it utc so they can be compared.
    start_date = start_date.replace(tzinfo=timezone.utc)

    assert milestone.due_date, "Milestone needs to have a Due Date set"
    due_date = isoparse(milestone.due_date)
    # We need to compare this with datetime objects, so we need a timezone
    due_date = due_date.replace(tzinfo=timezone.utc)

    # We don't use the milestone to get the merge requests, as we are
    # interested in all the ones NOT part of the milestone
    group = gl.groups.get(GROUP_NAME)

    # Grab all merge requests
    mrs = group.mergerequests.list(state="merged", all=True)

    # mapping of project_id => project object
    projects = projects_from_mrs(gl, mrs)
    for proj_id, proj in projects_from_list(gl).items():
        projects[proj_id] = proj

    # Maybe use dateutil.parse?

    for project in projects.values():
        with log_state(project=project.path_with_namespace):
            if project.path_with_namespace in IGNORE_MR_PROJECTS:
                _log.msg("Ignoring project")
                continue

            mrs = project.mergerequests.list(
                state="merged", order_by="created_at", all=True
            )
            mrs = (m for m in mrs if not m.milestone)

            for mr in mrs:
                with log_state(mr_title=mr.title, mr_url=mr.web_url):
                    if not mr.merged_at:
                        _log.msg("No merged date, ignoring")
                        continue
                    merged_at = isoparse(mr.merged_at)
                    if start_date < merged_at < due_date:
                        mr.milestone_id = milestone.id
                        _log.msg("Assigning to milestone")
                        if not pretend:
                            try:
                                mr.save()
                            except Exception as e:
                                err = str(e)
                                _log.error("Failed to update", exception=err)


def milestone_release(gl, tag_name, dry_run):
    """Run manually to create a release in all projects"""
    assert tag_name.count(".") >= 2, "Tag should be a full version, v3.14.0"
    bind_contextvars(tag_name=tag_name)

    milestone_name = tag_name.rsplit(".", 1)[0]
    milestone = get_milestone(gl, milestone_name)
    mrs = milestone.merge_requests()
    merged_mrs = [m for m in mrs if m.state == "merged"]

    projects = projects_from_mrs(gl, merged_mrs)
    # Fill up with our "ALWAYS CREATE PROJECT"
    for name in RELEASE_PROJECTS:
        _log.info("Looking up id for", project_name=name)
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

    def make_text(incoming, fobj, release=True):
        """Creates a text representation of a changelog"""
        fmt_release = "* [{text}]({url}) \n"
        fmt_tag = "* {url}: {text} \n"
        fmt_nourl = "* {text} \n"

        # Git internal tags just get plain text format issues
        our_lines = [l for l in incoming]

        if not our_lines:
            fobj.write("\n")
            fobj.write("No major changes")
        return

        for kind in Kind:
            lines = [l for l in our_lines if l.kind == kind]
            if not lines:
                continue
            fobj.write("\n")
            fobj.write(f"## {present_kind(kind)}: \n\n")
            for line in lines:
                if not line.slug:
                    txt = fmt_nourl.format(text=line.text)
                # Release text formatting
                elif release:
                    txt = fmt_release.format(text=line.text, url=line.slug)
                # tag text formatting
                else:
                    txt = fmt_tag.format(text=line.text, url=line.slug)
                fobj.write(txt)

    for project in projects.values():
        if project.path_with_namespace in IGNORE_MR_PROJECTS:
            continue
        bind_contextvars(project=project.path_with_namespace, project_id=project.id)
        release = io.StringIO()
        tag = io.StringIO()
        tag.write(f"Release {tag_name}\n\n")
        release.write(f"Release {tag_name}\n")
        release.write("\n")
        release.write(f"Milestone: {milestone.web_url} \n\n")
        changelog = make_changelog(changes[project.id])

        make_text(changelog, tag, release=False)
        make_text(changelog, release, release=True)

        tag_message = tag.getvalue()
        release_message = release.getvalue()

        tag.close()
        release.close()
        del tag, release

        proj_name = project.path_with_namespace
        tag_prefs = {"tag_name": tag_name, "message": tag_message, "ref": "master"}
        bind_contextvars(tag_name=tag_name, tag_message=tag_message, tag_ref="master")
        if dry_run:
            _log.msg("Would create tag")
        else:
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
