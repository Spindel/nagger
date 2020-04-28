#!/usr/bin/env python3
"""Simple CI helper to remind people to set milestones"""
import os

import structlog
from urllib.parse import urlparse
from structlog.contextvars import bind_contextvars
from . import oauth


_log = structlog.get_logger(__name__)

GROUP_NAME = "ModioAB"
DEFAULT_API_URL = "https://gitlab.com/"
IGNORE_MR_PROJECTS = ["ModioAB/sysadmin", "ModioAB/clientconfig"]
RELEASE_PROJECTS = [
    "ModioAB/afase",
    "ModioAB/mytemp-backend",
    "ModioAB/modio-api",
    "ModioAB/zabbix-containers",
    "ModioAB/submit",
    "ModioAB/plagiation",
    "ModioAB/housekeeper",
    "ModioAB/containers",
    "ModioAB/grafana-datasource",
    "ModioAB/caramel-manager",
    "ModioAB/visualisation-editor",
    "ModioAB/nagger",
]


class NoToken(Exception):
    """No token in environment"""


def get_api_url():
    """Gets a api url from CI variables"""
    val = os.environ.get("CI_API_V4_URL", DEFAULT_API_URL)
    assert val, "Environment variable: CI_API_V4_URL missing"
    # CI_API_.. is a full path, we just need the scheme+domain.
    parsed_uri = urlparse(val)
    result = "{uri.scheme}://{uri.netloc}/".format(uri=parsed_uri)
    bind_contextvars(API_URL=result)
    return result


def get_api_token():
    """Gets a api token from CI variables"""
    val = os.environ.get("NAGGUS_KEY", "")
    val = val.strip()
    if not val:
        raise NoToken("Environment variable: NAGGUS_KEY is missing")
    return val


def get_env_gitlab():
    """Create a gitlab instance from CI variables"""
    from gitlab import Gitlab

    api_url = get_api_url()
    api_token = get_api_token()
    gl = Gitlab(api_url, api_token)
    # Authenticate so we can get our .user. data
    gl.auth()
    bind_contextvars(API_USER=gl.user.username)
    _log.msg("api token")
    return gl


def get_oauth_gitlab():
    """Attempt to use oauth to get gitlab"""
    from gitlab import Gitlab

    api_url = get_api_url()
    oa = oauth.GLOauth()
    token = oa.get_token()
    gl = Gitlab(api_url, oauth_token=token)
    gl.auth()
    bind_contextvars(API_USER=gl.user.username)
    _log.msg("oauth session")
    return gl


def gitlab_file_exists(project, file_path, branch="master"):
    """Ensure a file exists in the path for the project"""
    from gitlab.exceptions import GitlabGetError

    try:
        return project.files.get(file_path=file_path, ref=branch)
    except GitlabGetError:
        return None
