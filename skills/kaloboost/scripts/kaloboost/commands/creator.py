"""`boost creator` — resolve TikTok creators to Kaloboost ids, read profiles."""

from __future__ import annotations

import re
import urllib.parse

from .. import api, render
from ..core import Command
from ..errors import UsageError
from . import common

RESOLVE_MAX = 100
BATCH_MAX = 100
_USER_ID = re.compile(r"^\d{6,}$")


def _resolve_item(raw: str, region: str) -> dict:
    """`7491234567890123456` -> creator_user_id; `@name` / `name` -> handle."""
    item = {"external_request_id": raw, "shop_region": region}
    if raw.startswith("uid:"):
        item["creator_user_id"] = raw[4:]
    elif _USER_ID.match(raw):
        item["creator_user_id"] = raw
    else:
        item["handle"] = raw
    return item


def resolve(cfg, opts, args):
    region = common.region(opts)
    inputs = common.ids(args, "creator", RESOLVE_MAX)
    body = {"items": [_resolve_item(x, region) for x in inputs]}
    data = api.request(cfg, "POST", "/creator-identities/resolve", body=body).get("data") or {}
    results = data.get("results") if isinstance(data, dict) else None
    results = results or []
    if opts.get("json"):
        common.dump_json(data)
        return 0
    display = []
    for r in results:
        c = r.get("creator") or {}
        display.append(
            {
                "input": r.get("external_request_id"),
                "status": r.get("status"),
                "match_basis": r.get("match_basis"),
                "creator_oecuid": c.get("creator_oecuid"),
                "handle": c.get("handle"),
                "creator_user_id": c.get("creator_user_id"),
                "gmv_range": c.get("gmv_range"),
            }
        )
    render.emit_table(
        "creators", display,
        ("input", "status", "match_basis", "creator_oecuid", "handle", "creator_user_id", "gmv_range"),
    )
    hints = [f"Run `boost creator get <creator_oecuid> --region {region}` for profile, contact and metrics"]
    if any(r.get("status") == "AMBIGUOUS" for r in results):
        hints.append("AMBIGUOUS = several candidates; retry with the numeric TikTok user id instead of the handle")
    if any(r.get("status") == "NOT_FOUND" for r in results):
        hints.append(f"NOT_FOUND only searched region {region}; try --region for the creator's own market")
    render.emit_help(hints)
    return 0


def _flat_profile(c: dict) -> dict:
    ident, prof, met = c.get("identity") or {}, c.get("profile") or {}, c.get("metrics") or {}
    return {
        "creator_oecuid": c.get("creator_oecuid"),
        "handle": ident.get("handle"),
        "nickname": prof.get("nickname"),
        "category": prof.get("category"),
        "followers": met.get("follower_count"),
        "median_views": met.get("video_med_view_cnt"),
        "gmv_range": met.get("gmv_range"),
        "email": prof.get("contact_email"),
        "phone": prof.get("contact_phone"),
    }


def get(cfg, opts, args):
    region = common.region(opts)
    oecuids = common.ids(args, "creator_oecuid", BATCH_MAX)
    if len(oecuids) == 1:
        path = "/creators/" + urllib.parse.quote(oecuids[0], safe="")
        data = api.request(cfg, "GET", path, params={"shop_region": region}).get("data") or {}
        if opts.get("json"):
            common.dump_json(data)
            return 0
        render.emit_detail("creator", data)
        render.emit_help(
            [
                "gmv is 30-day revenue in local currency and is exact for only ~2-5% of creators — "
                "\"0\" or null means unknown, not zero; show gmv_range instead",
                "gmv_range is a display label — never parse or sort by it",
            ]
        )
        return 0

    data = api.request(
        cfg, "POST", "/creators:batchGet", body={"shop_region": region, "creator_oecuids": oecuids}
    ).get("data")
    if opts.get("json"):
        common.dump_json(data)
        return 0
    if isinstance(data, dict):
        data = data.get("results") or data.get("creators") or data.get("items") or []
    rows = []
    for item in data or []:
        if not isinstance(item, dict):
            continue
        c = item.get("creator") if isinstance(item.get("creator"), dict) else item
        row = _flat_profile(c)
        row["creator_oecuid"] = row["creator_oecuid"] or item.get("creator_oecuid")
        row["status"] = item.get("status") or ("FOUND" if c.get("identity") else None)
        rows.append(row)
    fields = ("creator_oecuid", "status", "handle", "nickname", "followers", "median_views", "gmv_range", "email")
    render.emit_table("creators", rows, fields)
    render.emit_help(["NOT_FOUND = not in this --region's creator table; other regions are not searched"])
    return 0


def _get_args_guard(cfg, opts, args):
    if any(a.startswith("@") for a in args):
        raise UsageError(
            "`creator get` takes creator_oecuid values, not handles",
            ["Resolve handles first: `boost creator resolve @handle --region US`"],
        )
    return get(cfg, opts, args)


COMMANDS = [
    Command(
        path="creator resolve",
        summary="Match TikTok handles / numeric user ids to Kaloboost creator ids (creator_oecuid)",
        handler=resolve,
        flags=[common.region_flag()],
        positional="@handle|user_id",
        pos_min=1,
        pos_max=None,
        examples=[
            "boost creator resolve @demo_creator --region US",
            "boost creator resolve 7491234567890123456 @another --region GB",
        ],
    ),
    Command(
        path="creator get",
        summary="Creator profile: handle, nickname, contact email/phone, followers, GMV band",
        handler=_get_args_guard,
        flags=[common.region_flag()],
        positional="creator_oecuid",
        pos_min=1,
        pos_max=None,
        examples=["boost creator get cr_01J6... --region US", "boost creator get <id1> <id2> --region US"],
    ),
]
