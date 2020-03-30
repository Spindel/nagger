#!/usr/bin/env python3
"""Simple cli part for nagger"""
import os
import sys

import click
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


def _prompt_milestone(milestone: str) -> str:
    """Helper for interactive use of prompting for milestone."""
    if milestone:
        return milestone
    ok_milestones = release.get_milestones()
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
    ci_bot.mr_nag()


@bot.command()
def tag_to_release():
    """Turn a tag to a release object."""
    ci_bot.release_tag()


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
    milestone = _prompt_milestone(milestone)
    release.milestone_changelog(milestone)


@milestone.command()
@click.option("-n", "--dry-run", is_flag=True)
@click.argument("milestone", required=False)
@click.pass_context
def fixup(ctx, dry_run, milestone):
    """Stomp all over the milestone and attempt to fix Merge requests and
    issues."""
    setup_logging()
    milestone = _prompt_milestone(milestone)
    release.milestone_fixup(milestone, dry_run)


@milestone.command()
@click.option("-n", "--dry-run", is_flag=True)
@click.argument("tag-name")
def tag_release(dry_run, tag_name):
    """Try to tag all projects involved with the milestone."""
    assert tag_name.count(".") >= 2, "A full tag name, eg v3.15.0"
    release.milestone_release(tag_name, dry_run)


cli = click.CommandCollection(sources=[milestone, bot])
