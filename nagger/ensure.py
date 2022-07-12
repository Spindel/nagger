from structlog import get_logger
from structlog.contextvars import bind_contextvars

_log = get_logger(__name__)


def gitlab_file_exists(project, file_path, branch="main"):
    """Ensure a file exists in the path for the project"""
    from gitlab.exceptions import GitlabGetError

    try:
        return project.files.get(file_path=file_path, ref=branch)
    except GitlabGetError:
        return None


def ensure_branch(project, branch_name):
    """Make sure a branch named "branch_name" exists in the project"""
    branches = project.branches.list()
    found_branches = [br for br in branches if br.name == branch_name]
    if found_branches:
        _log.info(
            "Found branch", branch_name=branch_name, branch_total=len(found_branches)
        )
        return found_branches[0]

    branch_obj = {
        "branch": branch_name,
        "ref": project.default_branch,
    }
    _log.info("Creating new branch", **branch_obj)
    branch = project.branches.create(branch_obj)
    return branch


def ensure_mr(project, mr_title):
    """Make sure an MR named mr_title  exists in the project"""
    mrs = project.mergerequests.list()
    found_mrs = [m for m in mrs if m.title == mr_title]
    if found_mrs:
        _log.info("Found mr", mr_title=mr_title, mr_total=len(found_mrs))
        return found_mrs[0]

    branch = ensure_branch(project, mr_title)

    mr_obj = {
        "title": mr_title,
        "source_branch": branch.name,
        "target_branch": project.default_branch,
        "remove_source_branch": True,
    }

    _log.info("MR creating", **mr_obj)
    mr = project.mergerequests.create(mr_obj)
    return mr


def ensure_file_content(project, branch, file_path, content, message):

    bind_contextvars(
        file_name=file_path, branch=branch, project=project.path_with_namespace
    )
    _log.info("Testing if file exists")
    file = gitlab_file_exists(project, file_path, branch)
    if file:
        _log.info("Updating file")
        file.content = content
        file.save(branch=branch, commit_message=message)
        return
    fobj = {
        "file_path": file_path,
        "branch": branch,
        "commit_message": message,
        "content": content,
    }
    _log.info("Creating file")
    _log.debug("Creating file", **fobj)
    project.files.create(fobj)
    return
