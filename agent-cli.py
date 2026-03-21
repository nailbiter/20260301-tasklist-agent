#!/usr/bin/env python
"""===============================================================================

        FILE: /Users/nailbiter/Documents/forgithub/20260301-tasklist-agent/agent-cli.py

       USAGE: (not intended to be directly executed)

 DESCRIPTION: 

     OPTIONS: ---
REQUIREMENTS: ---
        BUGS: ---
       NOTES: ---
      AUTHOR: Alex Leontiev (alozz1991@gmail.com)
ORGANIZATION: 
     VERSION: ---
     CREATED: 2026-03-21T20:51:04.083928
    REVISION: ---

==============================================================================="""

import click
from dotenv import load_dotenv
import os
from os import path
import logging

import agent_taskmaster


@click.group()
def agent_cli():
    pass


@agent_cli.command()
@click.option("-P", "--prefix", type=click.Choice(["task"]), required=True)
def sessions(prefix):
    click.echo(
        agent_taskmaster.make_new_session_or_fetch_existing(
            is_make_new=False, prefix=prefix
        )
    )


@agent_cli.command()
@click.option("-p", "--prompt", type=str, required=True)
@click.option("-S", "--session-id", type=str)
def taskmaster(prompt, session_id):
    return agent_taskmaster.ask_agent(prompt=prompt, session_id=session_id)


if __name__ == "__main__":
    fn = ".env"
    if path.isfile(fn):
        logging.warning(f"loading `{fn}`")
        load_dotenv(dotenv_path=fn)
    agent_cli()
