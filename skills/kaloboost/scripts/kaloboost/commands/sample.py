"""`boost sample` — free-sample requests, fulfillment, and the content creators posted."""

from __future__ import annotations

import urllib.parse

from .. import api, render
from ..core import Command, Flag
from . import common

FIELDS = (
    "sample_request_id", "creator_oecuid", "status", "product", "commission_rate",
    "videos", "lives", "applied_at", "updated_at",
)


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _row(s: dict) -> dict:
    products = s.get("products") or []
    title = products[0].get("product_title") if products and isinstance(products[0], dict) else None
    if len(products) > 1:
        title = f"{render.clip(title, 30)} (+{len(products) - 1})"
    ful = s.get("fulfillment") or {}
    return {
        "sample_request_id": s.get("sample_request_id"),
        "creator_oecuid": s.get("creator_oecuid"),
        "status": s.get("curr_status"),
        "product": render.clip(title, 40),
        "commission_rate": s.get("commission_rate"),
        "videos": ful.get("video_count"),
        "lives": ful.get("live_count"),
        "applied_at": (s.get("timeline") or {}).get("applied_at"),
        "updated_at": s.get("updated_at"),
    }


def sample_list(cfg, opts, args):
    shop = common.shop(cfg, opts)
    since = common.parse_when(opts.get("since"))
    rows, cursor, pages = common.fetch_pages(
        cfg, "/samples", {"shop_id": shop, "updated_from": since}, opts, stop_on_empty=True
    )
    dupes = len(rows)
    rows = common.dedupe_latest(rows, "sample_request_id")
    dupes -= len(rows)
    status = opts.get("status")
    if status:
        rows = [s for s in rows if s.get("curr_status") == status.upper()]
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": cursor})
        return 0
    base = common.again("sample list", *common.flag_pairs(shop=shop, since=since))
    if not rows:
        ctx = f"shop {shop}" + (f", updated since {since}" if since else "") + (f", status {status}" if status else "")
        render.emit_empty("samples", ctx, common.page_hints(rows, cursor, pages, base, opts, []))
        return 0
    render.emit_table("samples", [_row(s) for s in rows], FIELDS)
    tally: dict = {}
    for s in rows:
        tally[s.get("curr_status")] = tally.get(s.get("curr_status"), 0) + 1
    hints = ["statuses: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1]))]
    if dupes:
        hints.append(f"{dupes} duplicate rows merged (kept the latest updated_at per id)")
    if status:
        hints.append("--status filters the fetched page(s) locally; add --all to scan the whole shop")
    hints += [
        f"Posted videos/lives with views and orders: `boost sample contents <sample_request_id> --shop {shop}`",
        "No status is final — COMPLETED/CANCELED/EXPIRED can still change; curr_status is the truth",
    ]
    if since:
        hints.append("--since can miss some changes (expiry, new content on finished samples); drop it for a full scan")
    render.emit_help(common.page_hints(rows, cursor, pages, base, opts, hints))
    return 0


def sample_get(cfg, opts, args):
    shop = common.shop(cfg, opts)
    data = api.request(cfg, "GET", f"/samples/{_q(args[0])}", params={"shop_id": shop}).get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("sample", data)
    hints = [f"Posted content: `boost sample contents {data.get('sample_request_id') or args[0]} --shop {shop}`"]
    if data.get("sample_request_id") and data["sample_request_id"] != args[0]:
        hints.insert(0, f"{args[0]} was merged into {data['sample_request_id']} — use the new id from now on")
    hints.append("delivered_time / delivered_at are always null today — judge delivery by curr_status")
    render.emit_help(hints)
    return 0


def contents(cfg, opts, args):
    shop = common.shop(cfg, opts)
    sid = args[0]
    rows, cursor, pages = common.fetch_pages(cfg, f"/samples/{_q(sid)}/contents", {"shop_id": shop}, opts)
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": cursor})
        return 0
    if not rows:
        render.emit_empty("contents", f"sample {sid}, shop {shop}", ["The creator has not posted for this sample yet"])
        return 0
    display = []
    for c in rows:
        m = c.get("metrics") or {}
        display.append(
            {
                "type": c.get("content_type"),
                "channel_content_id": c.get("channel_content_id"),
                "published_at": c.get("published_at"),
                "views": m.get("view_count"),
                "likes": m.get("like_count"),
                "comments": m.get("comment_count"),
                "orders": m.get("paid_order_count"),
                "url": c.get("video_url"),
            }
        )
    render.emit_table(
        "contents", display,
        ("type", "channel_content_id", "published_at", "views", "likes", "comments", "orders", "url"),
    )
    hints = ["Metrics are snapshots, often stale for older posts — don't add up values from different calls"]
    base = common.again("sample contents", sid, *common.flag_pairs(shop=shop))
    render.emit_help(common.page_hints(rows, cursor, pages, base, opts, hints))
    return 0


STATUSES = (
    "APPLY_TO_REVIEW", "READY_TO_SHIP", "SHIPPED", "CONTENT_PENDING", "COMPLETED",
    "REJECTED", "EXPIRED", "UNFULFILLED", "CANCELED", "UNMAPPED",
)

COMMANDS = [
    Command(
        path="sample list",
        summary="Sample requests of a shop with status, product, commission and content counts",
        handler=sample_list,
        flags=[
            common.shop_flag(),
            common.since_flag(),
            Flag("--status", "keep only this curr_status (local filter)", choices=STATUSES, metavar="STATUS"),
            *common.page_flags(),
        ],
        examples=[
            "boost sample list --shop <SHOP_ID> --since 7d",
            "boost sample list --shop <SHOP_ID> --all --status CONTENT_PENDING",
        ],
    ),
    Command(
        path="sample get",
        summary="One sample request: products/SKUs, fulfillment, status timeline",
        handler=sample_get,
        flags=[common.shop_flag()],
        positional="sample_request_id",
        pos_min=1,
        pos_max=1,
        examples=["boost sample get <SAMPLE_ID> --shop <SHOP_ID>"],
    ),
    Command(
        path="sample contents",
        summary="Videos and lives a creator posted for a sample, with views, likes, orders",
        handler=contents,
        flags=[common.shop_flag(), *common.page_flags(default_limit=50)],
        positional="sample_request_id",
        pos_min=1,
        pos_max=1,
        examples=["boost sample contents <SAMPLE_ID> --shop <SHOP_ID>"],
    ),
]
