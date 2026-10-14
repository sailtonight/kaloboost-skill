"""`boost content` — videos and lives creators posted for a shop, with metric snapshots."""

from __future__ import annotations

import urllib.parse

from .. import api, render
from ..core import Command, Flag
from . import common

FIELDS = (
    "content_id", "type", "creator_oecuid", "channel_content_id", "published_time",
    "views", "likes", "orders", "gmv", "updated_at",
)


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _gmv(m: dict) -> str | None:
    if m.get("direct_gmv_amount") is None:
        return None
    return f"{m['direct_gmv_amount']} {m.get('currency_code') or ''}".strip()


def _row(c: dict) -> dict:
    m = c.get("metrics") or {}
    return {
        "content_id": c.get("content_id"),
        "type": c.get("content_type"),
        "creator_oecuid": c.get("creator_oecuid"),
        "channel_content_id": c.get("channel_content_id"),
        "published_time": c.get("published_time"),
        "views": m.get("watch_cnt"),
        "likes": m.get("like_cnt"),
        "orders": m.get("order_cnt"),
        "gmv": _gmv(m),
        "updated_at": c.get("updated_at"),
    }


def content_list(cfg, opts, args):
    shop = common.shop(cfg, opts)
    since = common.parse_when(opts.get("since"))
    pub_from = common.parse_when(opts.get("published_from"), "--published-from")
    pub_to = common.parse_when(opts.get("published_to"), "--published-to")
    creator, ctype = opts.get("creator"), opts.get("type")
    params = {
        "shop_id": shop, "creator_oecuid": creator, "content_type": ctype,
        "published_time_from": pub_from, "published_time_to": pub_to, "updated_from": since,
    }
    rows, cursor, pages = common.fetch_pages(cfg, "/creator-content", params, opts)
    if opts.get("all"):
        rows = common.dedupe_latest(rows, "content_id")
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": cursor})
        return 0
    base = common.again("content list", *common.flag_pairs(
        shop=shop, creator=creator, type=ctype, published_from=pub_from, published_to=pub_to, since=since,
    ))
    if not rows:
        render.emit_empty("contents", f"shop {shop}", common.page_hints(rows, cursor, pages, base, opts, []))
        return 0
    render.emit_table("contents", [_row(c) for c in rows], FIELDS)
    hints = [
        "Metrics are cumulative snapshots and can go down (refunds, TikTok backfill) — keep the latest, never add up",
        f"Full record with sample / collaboration links: `boost content get <content_id> --shop {shop}`",
    ]
    render.emit_help(common.page_hints(rows, cursor, pages, base, opts, hints))
    return 0


def content_get(cfg, opts, args):
    shop = common.shop(cfg, opts)
    data = api.request(cfg, "GET", f"/creator-content/{_q(args[0])}", params={"shop_id": shop}).get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("content", data)
    render.emit_help([
        "sample_request_id / outreach_cooperate_id are null when the link can't be established — not guessed",
        "Metrics are a snapshot as of metrics.stats_time",
    ])
    return 0


COMMANDS = [
    Command(
        path="content list",
        summary="Creator videos and lives for a shop, with views, likes, orders and GMV",
        handler=content_list,
        flags=[
            common.shop_flag(),
            Flag("--creator", "only this creator_oecuid", metavar="CREATOR_OECUID"),
            Flag("--type", "only this content type, e.g. VIDEO or LIVE", metavar="TYPE"),
            Flag("--published-from", "published at or after: 7d | yyyy-MM-dd | ISO", metavar="WHEN"),
            Flag("--published-to", "published before: 7d | yyyy-MM-dd | ISO", metavar="WHEN"),
            common.since_flag(),
            *common.page_flags(),
        ],
        examples=[
            "boost content list --shop <SHOP_ID> --published-from 30d --all",
            "boost content list --shop <SHOP_ID> --creator <CREATOR_OECUID>",
        ],
    ),
    Command(
        path="content get",
        summary="One piece of content: links to sample / collaboration, products, latest metrics",
        handler=content_get,
        flags=[common.shop_flag()],
        positional="content_id",
        pos_min=1,
        pos_max=1,
        examples=["boost content get <CONTENT_ID> --shop <SHOP_ID>"],
    ),
]
