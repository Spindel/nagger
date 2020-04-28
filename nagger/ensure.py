from structlog import get_logger

_log = get_logger(__name__)


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
        "ref": "master",
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
        "target_branch": "master",
        "remove_source_branch": True,
    }

    _log.info("MR creating", **mr_obj)
    mr = project.mergerequests.create(mr_obj)
    return mr
