"""`boost capabilities` and `boost shops` — what this key can reach."""

from __future__ import annotations

from .. import api, render
from ..core import Command
from . import common

OPEN = ("AVAILABLE", "PILOT")


def capabilities(cfg, opts, args):
    data = api.request(cfg, "GET", "/capabilities").get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    caps = data.get("capabilities") or {}
    rows = [{"capability": k, "status": v, "callable": v in OPEN} for k, v in caps.items()]
    render.emit_table("capabilities", rows, ("capability", "status", "callable"))
    regions = data.get("shop_regions") or []
    rates = data.get("rate_limits") or {}
    render.out(f"creator_regions[{len(regions)}]: {','.join(regions)}")
    if rates:
        render.out(
            "rate_limits: "
            + " · ".join(f"{k} {v.get('limit')}/{v.get('window_seconds')}s" for k, v in rates.items() if isinstance(v, dict))
        )
    render.emit_help(
        [
            "AVAILABLE/PILOT can be called; PLANNED/UNAVAILABLE answer 503 — don't retry those",
            "Shop-level features (outreach, collab, sample, order) also depend on each shop: run `boost shops`",
        ]
    )
    return 0


def shops(cfg, opts, args):
    rows, cursor, pages = common.fetch_pages(cfg, "/shops", {}, opts)
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": cursor})
        return 0
    if not rows:
        render.emit_empty(
            "shops", "no ACTIVE + BOUND shops for this key",
            ["Shops must be bound in Kaloboost by the company this key belongs to"],
        )
        return 0
    display = [
        {
            "shop_id": r.get("shop_id"),
            "shop_name": r.get("shop_name"),
            "region": r.get("shop_region"),
            "time_zone": r.get("time_zone"),
            "capabilities": common.joined(r.get("capabilities")),
        }
        for r in rows
    ]
    render.emit_table("shops", display, ("shop_id", "shop_name", "region", "time_zone", "capabilities"))
    hints = [
        "Pass a shop_id as --shop to outreach / collab / sample / order / event commands",
        "Save a default: `boost config set --shop <SHOP_ID>`",
        "AFFILIATE_ATTRIBUTION missing on a US/ID/TH/MY/VN/PH/SG shop = TikTok Shop Open API not authorized in Kaloboost",
    ]
    render.emit_help(common.page_hints(rows, cursor, pages, "boost shops", opts, hints))
    return 0


COMMANDS = [
    Command(
        path="capabilities",
        summary="Which Kaloboost features are open for this key, creator regions, rate limits",
        handler=capabilities,
        examples=["boost capabilities"],
    ),
    Command(
        path="shops",
        summary="Shops bound in Kaloboost that this key can read (ids for --shop)",
        handler=shops,
        flags=common.page_flags(default_limit=50),
        examples=["boost shops", "boost shops --all"],
    ),
]
