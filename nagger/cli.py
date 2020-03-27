#!/usr/bin/env python3
"""Simple cli part for nagger"""
import os

import click
from . import (
    mr_nag,
    release_tag,
    milestone_changelog,
    milestone_fixup,
    milestone_release,
    setup_logging,
)


@click.group()
@click.pass_context
def cli(ctx):
    """Main command"""
    setup_logging()
    global _log

    if ctx.invoked_subcommand != "debug-variables":
        if "NAGGUS_KEY" not in os.environ:
            ctx.fail("We expect NAGGUS_KEY environment variable to contain an API key")


@cli.command()
def debug_variables():
    debug_variables()


@cli.command()
@click.option("-n", "--dry-run", is_flag=True)
def nag(dry_run):
    """Merge request nagger. meant to be run in a CI job"""
    mr_nag()


@cli.command()
@click.option("-n", "--dry-run", is_flag=True)
def make_release(dry_run):
    release_tag()


@cli.command()
@click.argument("milestone")
def changelog(milestone):
    """Generate changelog for milestone"""
    milestone_changelog(milestone)


@cli.command()
@click.option("-n", "--dry-run", is_flag=True)
@click.argument("milestone")
def fixup(dry_run, milestone):
    """Stomp all over the milestone and attempt to fix Merge requests and
    issues."""
    milestone_fixup(milestone, dry_run)


@cli.command()
@click.option("-n", "--dry-run", is_flag=True)
@click.argument("tag-name")
def tag_release(dry_run, tag_name):
    """Try to tag all projects involved with the milestone."""
    assert tag_name.count(".") >= 2, "A full tag name, eg v3.15.0"
    milestone_release(tag_name, dry_run)
