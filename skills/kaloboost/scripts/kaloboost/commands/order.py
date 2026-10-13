"""`boost order` — TikTok Shop affiliate orders of a shop, read live from TikTok."""

from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation

from .. import render
from ..core import Command, Flag
from ..errors import UsageError
from . import common

WINDOW_MAX_DAYS = 90
DEFAULT_DAYS = 30

FIELDS = (
    "channel_order_id", "created_at", "product_id", "qty", "price", "creator",
    "content", "rate", "est_commission", "settlement", "returned",
)


def _window(opts) -> tuple[str, str]:
    now = datetime.datetime.now(datetime.timezone.utc)
    to = common.parse_when(opts.get("to"), "--to", now=now) or common.iso(now)
    frm = common.parse_when(opts.get("from"), "--from", now=now)
    if not frm:
        frm = common.iso(datetime.datetime.fromisoformat(to.replace("Z", "+00:00")) - datetime.timedelta(days=DEFAULT_DAYS))
    a = datetime.datetime.fromisoformat(frm.replace("Z", "+00:00"))
    b = datetime.datetime.fromisoformat(to.replace("Z", "+00:00"))
    if a >= b:
        raise UsageError(f"--from {frm} must be earlier than --to {to}")
    if b - a > datetime.timedelta(days=WINDOW_MAX_DAYS):
        raise UsageError(
            f"order window {frm} ~ {to} is longer than {WINDOW_MAX_DAYS} days",
            ["Split it into several windows of at most 90 days"],
        )
    return frm, to


def merge_orders(rows: list[dict]) -> list[dict]:
    """An order can straddle two pages (limit counts SKU lines): join its items."""
    merged: dict = {}
    order: list = []
    for o in rows:
        oid = o.get("channel_order_id")
        if oid not in merged:
            merged[oid] = dict(o, items=list(o.get("items") or []))
            order.append(oid)
        else:
            merged[oid]["items"].extend(o.get("items") or [])
    return [merged[k] for k in order]


def _dec(v) -> Decimal | None:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _add(totals: dict, money, times: int = 1) -> None:
    if not isinstance(money, dict):
        return
    amt = _dec(money.get("amount"))
    if amt is None:
        return
    cur = money.get("currency") or "?"
    totals[cur] = totals.get(cur, Decimal(0)) + amt * times


def _fmt(totals: dict) -> str:
    return " + ".join(f"{v.normalize():f} {k}" for k, v in totals.items()) or "0"


def orders(cfg, opts, args):
    shop = common.shop(cfg, opts)
    frm, to = _window(opts)
    rows, cursor, pages = common.fetch_pages(
        cfg, "/affiliate-orders", {"shop_id": shop, "created_from": frm, "created_to": to}, opts
    )
    merged = merge_orders(rows)
    if opts.get("json"):
        common.dump_json({"data": merged, "next_cursor": cursor})
        return 0
    base = common.again("order list", *common.flag_pairs(shop=shop, **{"from": frm, "to": to}))
    if not merged:
        render.emit_empty("orders", f"shop {shop}, created {frm} ~ {to}", common.page_hints(merged, cursor, pages, base, opts, []))
        return 0

    lines = []
    gmv: dict = {}
    est: dict = {}
    for o in merged:
        for it in o.get("items") or []:
            com = it.get("commission") or {}
            qty = it.get("quantity") or 0
            _add(gmv, it.get("price"), int(qty) if isinstance(qty, int) else 1)
            _add(est, (com.get("estimated") or {}).get("paid"))
            content = it.get("content") or {}
            lines.append(
                {
                    "channel_order_id": o.get("channel_order_id"),
                    "created_at": o.get("created_at"),
                    "product_id": it.get("channel_product_id"),
                    "qty": qty,
                    "price": common.money(it.get("price")),
                    "creator": (it.get("creator") or {}).get("username"),
                    "content": f"{content.get('type')}:{content.get('channel_content_id')}" if content else None,
                    "rate": com.get("rate"),
                    "est_commission": common.money((com.get("estimated") or {}).get("paid")),
                    "settlement": it.get("settlement_status"),
                    "returned": it.get("fully_returned"),
                }
            )
    render.emit_table("order_lines", lines, FIELDS)
    hints = [
        f"{len(merged)} orders, {len(lines)} SKU lines · GMV {_fmt(gmv)} · est. commission {_fmt(est)}",
        "Live from TikTok, not stored: settlement and refunds change later — re-pull the window instead of adding up runs",
        "creator is the TikTok username (authoritative); add --json for creator_oecuid, collaboration source, actual commission",
    ]
    if cursor:
        hints.append("The last order may continue on the next page — use --all for complete orders")
    render.emit_help(common.page_hints(merged, cursor, pages, base, opts, hints))
    return 0


COMMANDS = [
    Command(
        path="order list",
        summary="Affiliate orders by order time: product, creator, content, commission, settlement",
        handler=orders,
        flags=[
            common.shop_flag(),
            Flag("--from", f"order time from: 7d | yyyy-MM-dd | ISO (default {DEFAULT_DAYS} days before --to)", metavar="WHEN"),
            Flag("--to", "order time until, exclusive (default now)", metavar="WHEN"),
            *common.page_flags(default_limit=50),
        ],
        examples=[
            "boost order list --shop <SHOP_ID> --from 7d --all",
            "boost order list --shop <SHOP_ID> --from 2026-09-01 --to 2026-10-01 --all",
        ],
    ),
]
