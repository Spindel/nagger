#!/usr/bin/env python3
"""Simple cli part for nagger"""
import os
import sys

import click
from . import get_gitlab, get_oauth_gitlab, NoToken
from . import ci_bot
from . import release

import structlog.contextvars

log = structlog.get_logger()


def setup_logging():
    """Global state. Eat it"""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.format_exc_info,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M.%S", utc=False),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
    )
    structlog.contextvars.clear_contextvars()
    log.debug("Logging, debug, initialized")
    log.msg("log.msg initialized")


def _prompt_milestone(gl, milestone: str) -> str:
    """Helper for interactive use of prompting for milestone."""
    if milestone:
        return milestone
    ok_milestones = release.get_milestones(gl)
    choice = click.Choice(ok_milestones)
    milestone = click.prompt("Pick milestone", show_choices=True, type=choice)
    return milestone


@click.group()
def bot():
    """Bot (CI) commands"""
    setup_logging()


@bot.command()
def debug_variables():
    ci_bot.debug_variables()


@bot.command()
def nag():
    """Merge request nagger. meant to be run in a CI job"""
    setup_logging()
    gl = get_ci_gitlab()
    ci_bot.mr_nag(gl)


@bot.command()
def tag_to_release():
    """Turn a tag to a release object."""
    setup_logging()
    gl = get_ci_gitlab()
    ci_bot.release_tag(gl)


@click.group()
@click.pass_context
def milestone(ctx):
    """Main command"""
    setup_logging()

    if "NAGGUS_KEY" not in os.environ:
        ctx.fail("We expect NAGGUS_KEY environment variable to contain an API key")


@milestone.command()
@click.argument("milestone", required=False)
def changelog(milestone):
    """Generate changelog for milestone"""
    setup_logging()
    try:
        gl = get_ci_gitlab()
    except NoToken:
        gl = get_oauth_gitlab()

    milestone = _prompt_milestone(gl, milestone)
    release.milestone_changelog(gl, milestone)


@milestone.command()
@click.option("-n", "--dry-run", is_flag=True)
@click.argument("milestone", required=False)
@click.pass_context
def fixup(ctx, dry_run, milestone):
    """Stomp all over the milestone and attempt to fix Merge requests and
    issues."""
    setup_logging()
    try:
        gl = get_ci_gitlab()
    except NoToken:
        gl = get_oauth_gitlab()
    milestone = _prompt_milestone(gl, milestone)
    release.milestone_fixup(gl, milestone, dry_run)


@milestone.command()
@click.option("-n", "--dry-run", is_flag=True)
@click.argument("tag-name")
def tag_release(dry_run, tag_name):
    """Try to tag all projects involved with the milestone."""
    setup_logging()
    assert tag_name.count(".") >= 2, "A full tag name, eg v3.15.0"
    try:
        gl = get_ci_gitlab()
    except NoToken:
        gl = get_oauth_gitlab()
    release.milestone_release(gl, tag_name, dry_run)


cli = click.CommandCollection(sources=[milestone, bot])
