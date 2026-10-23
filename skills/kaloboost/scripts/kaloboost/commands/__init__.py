"""Command registry: every noun module contributes Command objects."""

from __future__ import annotations

from ..core import Command
from . import (
    account, attribution, chat, collab, content, creator, event, meta, order, outreach, resolve_job, sample, webhook,
)

COMMANDS: list[Command] = []
for _mod in (
    account, creator, resolve_job, outreach, chat, collab, sample, content, order, attribution, event, webhook, meta,
):
    COMMANDS.extend(_mod.COMMANDS)

# noun -> default subcommand when invoked bare (content first: `boost sample` == list)
DEFAULT_SUB = {
    "outreach": "list",
    "chat": "list",
    "collab": "list",
    "sample": "list",
    "content": "list",
    "order": "list",
    "attribution": "list",
    "event": "list",
    "webhook": "list",
    "config": "show",
}

ALIASES = {
    "caps": "capabilities",
    "shop": "shops",
    "creators": "creator",
    "chats": "chat",
    "collaboration": "collab",
    "collaborations": "collab",
    "samples": "sample",
    "contents": "content",
    "orders": "order",
    "attributions": "attribution",
    "events": "event",
    "webhooks": "webhook",
}
