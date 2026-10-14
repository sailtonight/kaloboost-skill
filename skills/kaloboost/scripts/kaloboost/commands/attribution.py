"""`boost attribution` — Kaloboost's per-order-line affiliate attribution records."""

from __future__ import annotations

import urllib.parse

from .. import api, render
from ..core import Command, Flag
from . import common

FIELDS = (
    "attribution_id", "order_id", "order_line_id", "creator", "content", "product",
    "order_status", "gmv", "est_commission", "final_commission", "updated_at",
)


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _amount(a: dict, key: str) -> str | None:
    if a.get(key) is None:
        return None
    return f"{a[key]} {a.get('currency') or ''}".strip()


def _row(r: dict) -> dict:
    creator, content, product = r.get("creator") or {}, r.get("content") or {}, r.get("product") or {}
    amounts = r.get("amounts") or {}
    return {
        "attribution_id": r.get("attribution_id"),
        "order_id": r.get("order_id"),
        "order_line_id": r.get("order_line_id"),
        "creator": creator.get("handle") or creator.get("creator_oecuid"),
        "content": f"{content.get('content_type')}:{content.get('channel_content_id')}" if content else None,
        "product": product.get("channel_product_id"),
        "order_status": r.get("order_status"),
        "gmv": _amount(amounts, "gmv"),
        "est_commission": _amount(amounts, "estimated_commission"),
        "final_commission": _amount(amounts, "final_commission"),
        "updated_at": r.get("updated_at"),
    }


def attribution_list(cfg, opts, args):
    shop = common.shop(cfg, opts)
    since = common.parse_when(opts.get("since"))
    until = common.parse_when(opts.get("until"), "--until")
    creator, order, content = opts.get("creator"), opts.get("order"), opts.get("content")
    params = {
        "shop_id": shop, "creator_oecuid": creator, "order_id": order, "channel_content_id": content,
        "updated_from": since, "updated_to": until,
    }
    rows, cursor, pages = common.fetch_pages(cfg, "/affiliate-attributions", params, opts)
    if opts.get("all"):
        rows = common.dedupe_latest(rows, "attribution_id")
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": cursor})
        return 0
    base = common.again("attribution list", *common.flag_pairs(
        shop=shop, creator=creator, order=order, content=content, since=since, until=until,
    ))
    if not rows:
        render.emit_empty("attributions", f"shop {shop}", common.page_hints(rows, cursor, pages, base, opts, [
            f"Live affiliate orders from TikTok: `boost order list --shop {shop}`",
        ]))
        return 0
    render.emit_table("attributions", [_row(r) for r in rows], FIELDS)
    hints = [
        "Orders and commission keep changing — the latest record per attribution_id wins, don't add up runs",
        "AMBIGUOUS creator identities are left unlinked (creator_oecuid null, raw TikTok id in --json)",
    ]
    render.emit_help(common.page_hints(rows, cursor, pages, base, opts, hints))
    return 0


def attribution_get(cfg, opts, args):
    shop = common.shop(cfg, opts)
    path = f"/affiliate-attributions/{_q(args[0])}"
    data = api.request(cfg, "GET", path, params={"shop_id": shop}).get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("attribution", data)
    render.emit_help(["Source is TikTok Shop's own attribution; estimated, final commission and refund are separate"])
    return 0


COMMANDS = [
    Command(
        path="attribution list",
        summary="Affiliate attribution per order line: creator, content, product, GMV, commission",
        handler=attribution_list,
        flags=[
            common.shop_flag(),
            Flag("--creator", "only this creator_oecuid", metavar="CREATOR_OECUID"),
            Flag("--order", "only this TikTok Shop order id", metavar="ORDER_ID"),
            Flag("--content", "only this TikTok video / live id", metavar="CHANNEL_CONTENT_ID"),
            common.since_flag(),
            Flag("--until", "only rows updated before: 7d | yyyy-MM-dd | ISO", metavar="WHEN"),
            *common.page_flags(),
        ],
        examples=[
            "boost attribution list --shop <SHOP_ID> --since 7d --all",
            "boost attribution list --shop <SHOP_ID> --order <ORDER_ID>",
        ],
    ),
    Command(
        path="attribution get",
        summary="One attribution record: amounts, settlement times, attribution rule",
        handler=attribution_get,
        flags=[common.shop_flag()],
        positional="attribution_id",
        pos_min=1,
        pos_max=1,
        examples=["boost attribution get <ATTRIBUTION_ID> --shop <SHOP_ID>"],
    ),
]
