"""`boost event` — change events of a shop (outreach tasks/recipients, collaborations, samples)."""

from __future__ import annotations

from .. import render
from ..core import Command, Flag
from ..errors import UsageError
from . import common

TYPES = ("outreach.task.updated", "outreach.recipient.updated", "collaboration.updated", "sample.updated")


def _state(e: dict):
    d = e.get("data") or {}
    for key in ("curr_status", "status", "cooperate_status", "send_status"):
        if d.get(key):
            return d[key]
    return None


def events(cfg, opts, args):
    cursor = opts.get("cursor")
    shop = None if cursor and not opts.get("shop") else common.shop(cfg, opts)
    types = None
    if opts.get("types"):
        types = common.ids([opts["types"]], "event type")
        bad = [t for t in types if t not in TYPES]
        if bad:
            raise UsageError(f"unsupported event type(s): {', '.join(bad)}", [f"v1 types: {', '.join(TYPES)}"])
        types = ",".join(types)
    since = common.parse_when(opts.get("since"))
    params = {"shop_id": shop, "types": types, "updated_from": since}
    if cursor:
        params = {"shop_id": shop}  # the cursor already pins shop and types
    rows, next_cursor, pages = common.fetch_pages(cfg, "/events", params, opts, stream=True)
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": next_cursor})
        return 0
    poll = [f"Poll for newer events later (≥5s): `boost event list --cursor {next_cursor}`"] if next_cursor else []
    if not rows:
        render.emit_empty("events", f"shop {shop or '(from cursor)'}" + (f", since {since}" if since else ""), poll + [
            "Events exist only after the shop was enabled for events, and are kept 30 days",
        ])
        return 0
    display = [
        {
            "occurred_at": e.get("occurred_at"),
            "type": e.get("type"),
            "resource_id": e.get("resource_id"),
            "version": e.get("resource_version"),
            "state": _state(e),
            "event_id": e.get("event_id"),
        }
        for e in rows
    ]
    render.emit_table("events", display, ("occurred_at", "type", "resource_id", "version", "state", "event_id"))
    hints = [
        "Each event carries the full object at detection time (--json); several changes may be merged into one",
        "Dedupe by event_id; per resource, ignore events with a lower version",
        *poll,
    ]
    render.emit_help(hints)
    return 0


COMMANDS = [
    Command(
        path="event list",
        summary="Change events of a shop, oldest first; kept 30 days",
        handler=events,
        flags=[
            common.shop_flag(),
            Flag("--types", "comma-separated: " + ",".join(TYPES), metavar="TYPES"),
            common.since_flag("that occurred"),
            *common.page_flags(default_limit=50),
        ],
        examples=[
            "boost event list --shop <SHOP_ID> --since 24h",
            "boost event list --shop <SHOP_ID> --types sample.updated --since 7d --all",
        ],
    ),
]
