#!/usr/bin/env python3
"""Simple CI helper to remind people to set milestones"""
from enum import IntEnum
from dataclasses import dataclass
from datetime import timezone, datetime
from typing import List, Optional
from urllib.parse import quote_plus

from dateutil.parser import isoparse

from structlog import get_logger
from structlog.contextvars import bind_contextvars, unbind_contextvars
from jinja2 import Environment, PackageLoader

from .logs import log_state
from . import GROUP_NAME, RELEASE_PROJECTS, IGNORE_MR_PROJECTS, IGNORE_RELEASE_PROJECTS

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

    slug: str
    text: str
    web_url: str
    labels: List[str]

    @property
    def kind(self) -> Kind:
        if "Feature" in self.labels:
            return Kind.Feature
        if "Bug" in self.labels:
            return Kind.Bug
        return Kind.misc

    @property
    def exposed(self) -> Exposed:
        """Returns the exposed state of a merge requests"""
        labels = {x.lower() for x in self.labels}
        if "internal" in labels:
            return Exposed.Internal
        return Exposed.External

    @classmethod
    def from_mr(cls, mr):
        slug = mr.references["full"]
        return cls(text=mr.title, slug=f"{slug}", web_url=mr.web_url, labels=mr.labels)


@dataclass(order=True)
class ProjectChangelog:
    """Project and its changelog"""

    name: str
    changes: List[ChangeLog]

    @property
    def internal(self) -> List[ChangeLog]:
        result = [x for x in self.changes if x.exposed == Exposed.Internal]
        return result

    @property
    def external(self) -> List[ChangeLog]:
        result = [x for x in self.changes if x.exposed == Exposed.External]
        return result


@dataclass
class Progress:
    completed: int
    total: int


@dataclass
class Issue:
    """Issue for Mermaid representation"""

    id: int
    link: str
    title: str
    state: str
    related: List["Issue"]
    progress: Optional[Progress]
    parent: Optional["Issue"]

    @property
    def closed(self) -> bool:
        return self.state == "closed"

    def __repr__(self):
        return f"{self.link}"

    @classmethod
    def from_issue(cls, raw, parent=None):
        progress = None
        if raw.has_tasks:
            task_stats = raw.task_completion_status
            progress = Progress(
                completed=task_stats["completed_count"], total=task_stats["count"],
            )

        # Start by creating it with an empty "related"
        issue = cls(
            id=raw.id,
            title=raw.title.replace('"', "'"),
            link=raw.references["full"],
            state=raw.state,
            progress=progress,
            related=[],
            parent=parent,
        )
        return issue


def present_issue(issue: Issue):
    if issue.closed:
        emoji = ":white_check_mark:"
    else:
        emoji = ":black_medium_square:"

    tasks = ""
    if issue.progress is not None:
        tasks = f"{issue.progress.completed}/{issue.progress.total}"

    return f"{emoji} {issue.title} {issue.link} {tasks}"


def present_kind(val: Kind):
    if val == Kind.Feature:
        return "New features"
    if val == Kind.Bug:
        return "Bug fixes"
    if val == Kind.misc:
        return "Misc changes"
    return "XXX: "


def get_milestone(gl, milestone_name):
    bind_contextvars(milestone_name=milestone_name, group_name=GROUP_NAME)
    group = gl.groups.get(GROUP_NAME)
    stones = group.milestones.list(title=milestone_name, as_list=True)
    # let it crash if no stones found
    milestone = stones[0]
    bind_contextvars(milestone_id=milestone.id)
    return milestone


def labels_to_md(labels: List[str]):
    """Convert a list of labels to GitLab markdown labels"""
    prefixed = (f"~{label}" for label in labels)
    result = " ".join(prefixed)
    return result


def get_template(template_name: str):
    environment = Environment(
        loader=PackageLoader("nagger", "templates"),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["present_kind"] = present_kind
    environment.filters["present_issue"] = present_issue
    environment.filters["labels2md"] = labels_to_md
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
        line = ChangeLog.from_mr(mr)
        result.append(line)
    return sorted(result)


def make_milestone_changelog(gl, milestone) -> List[ProjectChangelog]:
    """Grabs all MR for a milestone, returning a Dict mapping to changelogs"""
    mrs = milestone.merge_requests()
    merged_mr = [m for m in mrs if m.state == "merged"]

    # mapping of project_id => project object
    projects = projects_from_mrs(gl, merged_mr)
    # mapping of project_id => [ChangeLog, ChangeLog, ...]
    changes = {}

    for mr in merged_mr:
        changes.setdefault(mr.project_id, [])
        changes[mr.project_id].append(mr)

    result = []
    for project_id, merge_requests in changes.items():
        bind_contextvars(project_id=project_id, num_mrs=len(merge_requests))
        project = projects[project_id]

        changelog = make_changelog(merge_requests)
        pcl = ProjectChangelog(name=project.path_with_namespace, changes=changelog)
        result.append(pcl)
    unbind_contextvars("project_id", "num_mrs")
    return sorted(result)


def load_issues(gl, initial_issues) -> List[Issue]:
    """Load a list of issues and populates them, recursively.

    """
    seen = set()

    def load_issue(project_id, issue_iid, parent=None) -> Optional[Issue]:
        if (project_id, issue_iid) in seen:
            _log.debug(
                "Already seen",
                project_id=project_id,
                issue_iid=issue_iid,
                parent=parent,
            )
            return None

        seen.add((project_id, issue_iid))

        _log.debug(
            "load_issue", project_id=project_id, issue_iid=issue_iid, parent=parent
        )
        project = gl.projects.get(project_id)
        raw = project.issues.get(issue_iid)
        issue = Issue.from_issue(raw, parent=parent)

        # Recursively populate related items and append them to our related
        children = raw.links.list(as_list=False)
        for rel in children:
            child = load_issue(rel.project_id, rel.iid, parent=issue)
            if child is not None:
                issue.related.append(child)
        return issue

    results = []
    for obj in initial_issues:
        val = load_issue(project_id=obj.project_id, issue_iid=obj.iid)
        if val is not None:
            results.append(val)
    return results


def milestone_changelog(gl, milestone_name):
    """Stomps all over a milestone"""
    all_changes = make_milestone_changelog(gl, milestone_name)

    external_md = get_template("external.md")
    print("--8<--" * 10 + "\n")
    for proj in all_changes:
        templated = external_md.render(project=proj.name, changes=proj.external)
        print(templated)
    print("-->8--" * 10 + "\n")

    # Internal changes are more concise
    print("# Internal only changes\n")
    internal_md = get_template("internal.md")
    for proj in all_changes:
        templated = internal_md.render(project=proj.name, changes=proj.changes)
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
    for proj_id, proj in projects_from_list(gl).items():
        projects[proj_id] = proj

    changes = {}
    for project_id in projects:
        changes.setdefault(project_id, [])
    del project_id

    for mr in merged_mrs:
        changes[mr.project_id].append(mr)
    del mr, merged_mrs

    tag_txt = get_template("project.tag.txt")
    release_md = get_template("project.release.md")

    for project in projects.values():
        if project.path_with_namespace in IGNORE_RELEASE_PROJECTS:
            continue
        bind_contextvars(project=project.path_with_namespace, project_id=project.id)
        changelog = make_changelog(changes[project.id])

        tag_message = tag_txt.render(tag_name=tag_name, changes=changelog)
        release_message = release_md.render(
            milestone=milestone, tag_name=tag_name, changes=changelog
        )

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


WWW_PROJECT = "ModioAB/modio.se"


def changelog_homepage(gl, milestone_name, dry_run=True, www_project=WWW_PROJECT):
    from .ensure import ensure_mr
    from .ensure import ensure_file_content

    bind_contextvars(www_project=www_project, milestone_name=milestone_name)

    all_changes = make_milestone_changelog(gl, milestone_name)
    all_changes = resort_changes(all_changes)
    homepage_md = get_template("homepage.md")

    # here we hope we have a branch
    date = datetime.today().strftime("%Y-%m-%d")
    commit_message = "Nagger generated release notes"
    file_path = f"content/news/release-{milestone_name}.md"
    author = f"{gl.user.name}"

    content = homepage_md.render(
        milestone_name=milestone_name, author=author, date=date, projects=all_changes
    )
    project = gl.projects.get(www_project)
    if dry_run:
        print("DRY RUN:", file_path)
        print(content)
        return

    mr = ensure_mr(project, milestone_name)
    ensure_file_content(
        project=project,
        branch=mr.source_branch,
        file_path=file_path,
        content=content,
        message=commit_message,
    )
    _log.info("Homepage article updated")


WIKI_PROJECT = "ModioAB/agile"

IMPORTANT_PROJECTS = {
    "ModioAB/afase",
    "ModioAB/plagiation",
    "ModioAB/submit",
    "ModioAB/modio-api",
    "ModioAB/mytemp-backend",
}


def resort_changes(changes: List[ProjectChangelog]) -> List[ProjectChangelog]:
    """Morphs changes to list projects we care for first"""
    offset = 0
    for project in changes:
        if project.name in IMPORTANT_PROJECTS:
            changes.remove(project)
            changes.insert(offset, project)
            offset += 1
    return changes


def changelog_wiki(gl, milestone_name, dry_run=True, wiki_project=WIKI_PROJECT):
    milestone = get_milestone(gl, milestone_name)
    title = f"Release notes/{milestone_name}"
    bind_contextvars(wiki_project=wiki_project, milestone_name=milestone_name)

    all_changes = make_milestone_changelog(gl, milestone)
    all_changes = resort_changes(all_changes)
    wiki_md = get_template("wiki.md")
    content = wiki_md.render(milestone=milestone, projects=all_changes)

    project = gl.projects.get(wiki_project)
    ensure_wiki_page_with_content(project.wikis, title, content, dry_run)


def milestone_wiki(gl, milestone_name, dry_run=True, wiki_project=WIKI_PROJECT):
    bind_contextvars(wiki_project=wiki_project, milestone_name=milestone_name)
    agile = gl.projects.get(wiki_project)
    wikis = agile.wikis
    mermaid_title = f"Milestones/{milestone_name}"
    # prefer agile-project milestone
    mss = agile.milestones.list(title=milestone_name, state="active", as_list=True)
    if len(mss) > 0:
        ms = mss[0]
    else:
        # fallback to group milestone
        ms = get_milestone(gl, milestone_name)
    initial_issues = [x for x in ms.issues()]

    # Load and populate a tree of issues
    issues = load_issues(gl, initial_issues)

    # Load our template and render it
    issue_md = get_template("issue_tree.md")
    issue_content = issue_md.render(milestone=ms, issues=issues)

    # Load our Mermaid chart and render it
    mermaid_md = get_template("mermaid_chart.md")
    mermaid_content = mermaid_md.render(issues=issues)

    # Join them together with a HR
    content = "\n".join((issue_content, "", "---", "", mermaid_content))
    ensure_wiki_page_with_content(wikis, mermaid_title, content, dry_run)


def ensure_wiki_page_with_content(wikis, title, content, dry_run=True):
    from gitlab.exceptions import GitlabGetError

    bind_contextvars(wiki_page_title=title)
    page = None
    try:
        page = wikis.get(title)
        _log.info("Will update wiki page")
    except GitlabGetError:
        _log.info("Will create wiki page")
        pass

    if dry_run:
        _log.info("DRY run wiki page")
        print(content)
    else:
        if not page:
            wikis.create({"title": title, "content": content})
        else:
            # page.save() does not url-encode slashes properly
            # so this is a workaround:
            wikis.update(quote_plus(page.slug), {"title": title, "content": content})
        _log.msg("wiki page successfully upserted", content=content)
