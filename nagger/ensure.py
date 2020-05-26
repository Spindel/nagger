from structlog import get_logger
from structlog.contextvars import bind_contextvars

from urllib.parse import quote_plus

_log = get_logger(__name__)


def gitlab_file_exists(project, file_path, branch="master"):
    """Ensure a file exists in the path for the project"""
    from gitlab.exceptions import GitlabGetError

    try:
        return project.files.get(file_path=file_path, ref=branch)
    except GitlabGetError:
        return None


def ensure_branch(project, branch_name, dry_run=True):
    """Make sure a branch named "branch_name" exists in the project"""
    found_branches = project.branches.list(search=branch_name)
    if len(found_branches) > 0:
        _log.info(
            "Found branch", branch_name=branch_name, branch_total=len(found_branches)
        )
        return found_branches[0]

    branch_obj = {
        "branch": branch_name,
        "ref": "master",
    }
    _log.info("Creating new branch", **branch_obj)
    if dry_run:
        _log.info("DRY-RUN")
        return project.branches.get(
            "master", lazy=True
        )  # just to return master as Branch.
    branch = project.branches.create(branch_obj)
    return branch


def ensure_tag(project, tag_name, ref="master", dry_run=True):
    from gitlab.exceptions import GitlabGetError

    try:
        tag = project.tags.get(tag_name)
        _log.info("Tag exists")
        return tag
    except GitlabGetError:
        _log.info("Will create tag", tag_name=tag_name, ref=ref)
        if not dry_run:
            return project.tags.create({"tag_name": tag_name, "ref": ref})
        _log.info("DRY-RUN")
        return project.tags.get(-7, lazy=True)


def ensure_mr(project, mr_title, dry_run=True):
    """Make sure an MR named mr_title  exists in the project"""
    found_mrs = project.mergerequests.list(search=mr_title)
    if len(found_mrs) > 0:
        _log.info("Found mr", mr_title=mr_title, mr_total=len(found_mrs))
        return found_mrs[0]

    branch = ensure_branch(project, mr_title, dry_run)

    mr_obj = {
        "title": mr_title,
        "source_branch": branch.name,
        "target_branch": "master",
        "remove_source_branch": True,
    }

    _log.info("MR creating", **mr_obj)
    if dry_run:
        _log.info("DRY-RUN")
        mr = project.mergerequests.get(-3, lazy=True)  # mock MR
        mr.source_branch = branch.name
        mr.title = mr_title
        return mr
    mr = project.mergerequests.create(mr_obj)

    return mr


def ensure_file_content(project, branch, file_path, content, message, dry_run=True):

    bind_contextvars(
        file_name=file_path, branch=branch, project=project.path_with_namespace
    )
    _log.info("Testing if file exists")
    file = gitlab_file_exists(project, file_path, branch)
    if file:
        _log.info("Updating file")
        file.content = content
        if dry_run:
            _log.debug("DRY-RUN: update ", branch=branch, message=message)
            return
        file.save(branch=branch, commit_message=message)
        return
    file_obj = {
        "file_path": file_path,
        "branch": branch,
        "commit_message": message,
        "content": content,
    }
    _log.info("Creating file")
    if dry_run:
        _log.debug("DRY-RUN: would create file", **file_obj)
        return
    project.files.create(file_obj)
    return


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
