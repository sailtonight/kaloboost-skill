"""`boost collab` — collaboration records: who a shop reached and whether it converted."""

from __future__ import annotations

import re

from .. import api, render
from ..core import Command
from ..errors import UsageError
from . import common

_ID = re.compile(r"^\d{1,32}$")

FIELDS = (
    "outreach_cooperate_id", "creator_oecuid", "method", "cooperate_status",
    "outreach_result", "task_name", "outreach_time", "updated_at",
)


def _row(c: dict) -> dict:
    return {
        "outreach_cooperate_id": c.get("outreach_cooperate_id"),
        "creator_oecuid": c.get("creator_oecuid"),
        "method": c.get("outreach_method"),
        "cooperate_status": c.get("cooperate_status"),
        "outreach_result": c.get("outreach_result"),
        "task_name": render.clip(c.get("outreach_task_name"), 36),
        "outreach_time": c.get("outreach_time"),
        "updated_at": c.get("updated_at"),
    }


def collab_list(cfg, opts, args):
    shop = common.shop(cfg, opts)
    since = common.parse_when(opts.get("since"))
    rows, cursor, pages = common.fetch_pages(
        cfg, "/collaborations", {"shop_id": shop, "updated_from": since}, opts
    )
    raw = len(rows)
    rows = common.dedupe_latest(rows, "outreach_cooperate_id")
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": cursor})
        return 0
    base = common.again("collab list", *common.flag_pairs(shop=shop, since=since))
    if not rows:
        ctx = f"shop {shop}" + (f", updated since {since}" if since else "")
        hints = common.page_hints(rows, cursor, pages, base, opts, [])
        if cursor:
            hints.insert(0, "An empty page with a cursor is not the end (server time budget) — keep paging")
        render.emit_empty("collaborations", ctx, hints)
        return 0
    render.emit_table("collaborations", [_row(c) for c in rows], FIELDS)
    tally: dict = {}
    for c in rows:
        tally[c.get("cooperate_status")] = tally.get(c.get("cooperate_status"), 0) + 1
    hints = ["statuses: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1]))]
    if raw != len(rows):
        hints.append(f"{raw - len(rows)} duplicate rows merged (kept the latest updated_at per id)")
    hints += [
        "cooperate_status is the shop↔creator relationship; outreach_result is this one outreach (null for DMs)",
        "outreach_time / updated_at before 2026-09-11 may be ~8h late (known upstream issue)",
    ]
    render.emit_help(common.page_hints(rows, cursor, pages, base, opts, hints))
    return 0


def collab_get(cfg, opts, args):
    shop = common.shop(cfg, opts)
    cid = args[0].strip()
    if not _ID.match(cid):
        raise UsageError(f"outreach_cooperate_id must be 1-32 digits, got '{args[0]}'")
    data = api.request(cfg, "GET", f"/collaborations/{cid}", params={"shop_id": shop}).get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("collaboration", data)
    hints = []
    if data.get("outreach_task_id"):
        hints.append(f"Source task: `boost outreach get {data['outreach_task_id']} --shop {shop}`")
    render.emit_help(hints)
    return 0


COMMANDS = [
    Command(
        path="collab list",
        summary="Collaboration records of a shop (target invitations and DMs), deduplicated",
        handler=collab_list,
        flags=[common.shop_flag(), common.since_flag(), *common.page_flags()],
        examples=["boost collab list --shop <SHOP_ID> --since 7d --all"],
    ),
    Command(
        path="collab get",
        summary="One collaboration record",
        handler=collab_get,
        flags=[common.shop_flag()],
        positional="outreach_cooperate_id",
        pos_min=1,
        pos_max=1,
        examples=["boost collab get 871234567890123401 --shop <SHOP_ID>"],
    ),
]
