"""Command registry: every noun module contributes Command objects."""

from __future__ import annotations

from ..core import Command
from . import account, collab, creator, event, meta, order, outreach, sample

COMMANDS: list[Command] = []
for _mod in (account, creator, outreach, collab, sample, order, event, meta):
    COMMANDS.extend(_mod.COMMANDS)

# noun -> default subcommand when invoked bare (content first: `boost sample` == list)
DEFAULT_SUB = {
    "outreach": "list",
    "collab": "list",
    "sample": "list",
    "order": "list",
    "event": "list",
    "config": "show",
}

ALIASES = {
    "caps": "capabilities",
    "shop": "shops",
    "collaboration": "collab",
    "collaborations": "collab",
    "samples": "sample",
    "orders": "order",
    "events": "event",
}
