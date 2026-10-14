"""`boost webhook` — endpoints that receive this company's change events by HTTPS push."""

from __future__ import annotations

import datetime
import urllib.parse

from .. import api, render
from ..core import Command, Flag
from ..errors import UsageError
from . import common

FIELDS = ("endpoint_id", "status", "paused_reason", "url", "event_types", "shop_ids", "updated_at")
STATUSES = ("ACTIVE", "PAUSED")
SHOP_MAX = 100


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _row(e: dict) -> dict:
    return {
        "endpoint_id": e.get("endpoint_id"),
        "status": e.get("status"),
        "paused_reason": e.get("paused_reason"),
        "url": e.get("url"),
        "event_types": common.joined(e.get("event_types")),
        "shop_ids": common.joined(e.get("shop_ids")),
        "updated_at": e.get("updated_at"),
    }


def _shops(cfg, opts, required: bool) -> list[str] | None:
    values = opts.get("shop") or ([cfg.shop] if required and cfg.shop else [])
    if not values:
        if required:
            raise UsageError("--shop is required (repeat it or comma-separate for several shops)",
                             ["Run `boost shops` for shop ids"])
        return None
    return common.ids(values, "shop id", SHOP_MAX)


def _emit_endpoint(data: dict, opts, extra: list[str]) -> int:
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("webhook_endpoint", data)
    hints = list(extra)
    if data.get("secret"):
        hints.insert(0, "secret is shown only this once — store it now; it verifies the X-KB-Webhook-Signature header")
    render.emit_help(hints)
    return 0


def webhook_list(cfg, opts, args):
    data = api.request(cfg, "GET", "/webhook-endpoints").get("data") or []
    if opts.get("json"):
        common.dump_json({"data": data})
        return 0
    if not data:
        render.emit_empty("webhook_endpoints", "none yet", [
            "Create one: `boost webhook create --url https://<host>/<path> --shop <SHOP_ID>`",
        ])
        return 0
    render.emit_table("webhook_endpoints", [_row(e) for e in data], FIELDS)
    hints = []
    if any(e.get("status") == "PAUSED" for e in data):
        hints += [
            "PAUSED endpoints get no events (AUTO_4XX = paused after repeated 4xx from your receiver)",
            "Resume with `boost webhook update <endpoint_id> --status ACTIVE --yes`, "
            "then backfill with `boost webhook replay` — missed events are not resent on their own",
        ]
    hints.append("Secrets are never listed; `boost webhook rotate-secret <endpoint_id>` issues a new one")
    render.emit_help(hints)
    return 0


def create(cfg, opts, args):
    url = (opts.get("url") or "").strip()
    if not url:
        raise UsageError("--url is required (https, port 443, a public domain name)")
    body = {
        "url": url,
        "event_types": common.event_types(opts.get("types")) or list(common.EVENT_TYPES),
        "shop_ids": _shops(cfg, opts, required=True),
    }
    env = common.send(cfg, opts, "POST", "/webhook-endpoints", body=body)
    if env is None:
        return 0
    data = env.get("data") or {}
    return _emit_endpoint(data, opts, [
        f"Check delivery: `boost webhook test {data.get('endpoint_id')} --yes`",
        "Only events from now on are pushed; for history use `boost webhook replay` or `boost event list`",
    ])


def update(cfg, opts, args):
    body: dict = {}
    if opts.get("url"):
        body["url"] = opts["url"].strip()
    types = common.event_types(opts.get("types"))
    if types:
        body["event_types"] = types
    shops = _shops(cfg, opts, required=False)
    if shops:
        body["shop_ids"] = shops
    if opts.get("status"):
        body["status"] = opts["status"]
    if not body:
        raise UsageError("nothing to change", ["Pass at least one of --url --types --shop --status"])
    env = common.send(cfg, opts, "PATCH", f"/webhook-endpoints/{_q(args[0])}", body=body)
    if env is None:
        return 0
    hints = []
    if "shop_ids" in body:
        hints.append("--shop replaced the whole shop list; new shops only get events from now on")
    if body.get("status") == "ACTIVE":
        hints.append(f"Events missed while paused are not resent — `boost webhook replay {args[0]} --from <WHEN> --yes`")
    return _emit_endpoint(env.get("data") or {}, opts, hints)


def rotate_secret(cfg, opts, args):
    env = common.send(cfg, opts, "POST", f"/webhook-endpoints/{_q(args[0])}:rotateSecret")
    if env is None:
        return 0
    return _emit_endpoint(env.get("data") or {}, opts, [
        "For 24h (until previous_secret_expires_at) X-KB-Webhook-Signature is still signed with the old secret "
        "and X-KB-Webhook-Signature-Next with the new one — switch your receiver before then",
    ])


def test(cfg, opts, args):
    env = common.send(cfg, opts, "POST", f"/webhook-endpoints/{_q(args[0])}:test")
    if env is None:
        return 0
    data = env.get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("webhook_test", data)
    render.emit_help(["A webhook.test event is on its way to the endpoint (same signing and retries as real events)"])
    return 0


def replay(cfg, opts, args):
    frm = common.parse_when(opts.get("from"), "--from")
    if not frm:
        raise UsageError("--from is required (events are kept 30 days)")
    to = common.parse_when(opts.get("to"), "--to") or common.iso(datetime.datetime.now(datetime.timezone.utc))
    body: dict = {"occurred_from": frm, "occurred_to": to}
    types = common.event_types(opts.get("types"))
    if types:
        body["event_types"] = types
    env = common.send(cfg, opts, "POST", f"/webhook-endpoints/{_q(args[0])}:replay", body=body)
    if env is None:
        return 0
    data = env.get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("webhook_replay", data)
    render.emit_help([
        "Replayed events keep their event_id — dedupe on it; they queue behind live events and can take hours",
        "One replay per endpoint at a time; there is no progress API",
    ])
    return 0


def _endpoint_cmd(path: str, summary: str, handler, flags: list, example: str) -> Command:
    return Command(
        path=path, summary=summary, handler=handler,
        flags=[*flags, common.key_flag(), common.yes_flag()],
        positional="endpoint_id", pos_min=1, pos_max=1, examples=[example],
    )


_TYPES_FLAG = Flag("--types", "comma-separated: " + ",".join(common.EVENT_TYPES), metavar="TYPES")

COMMANDS = [
    Command(
        path="webhook list",
        summary="Webhook endpoints of this key: url, status, subscribed events and shops",
        handler=webhook_list,
        examples=["boost webhook list"],
    ),
    Command(
        path="webhook create",
        summary="Create an endpoint that receives change events (prints the request; --yes sends)",
        handler=create,
        flags=[
            Flag("--url", "HTTPS receiver: port 443, a public domain name (no IPs)", metavar="URL"),
            Flag("--types", "comma-separated (default: all): " + ",".join(common.EVENT_TYPES), metavar="TYPES"),
            Flag("--shop", "shop to subscribe; repeat or comma-separate, max 100 (default: config shop)",
                 kind="multi", default=[], metavar="SHOP_ID"),
            common.key_flag(),
            common.yes_flag(),
        ],
        examples=["boost webhook create --url https://hooks.example.com/kaloboost --shop <SHOP_ID> --yes"],
    ),
    _endpoint_cmd(
        "webhook update", "Change an endpoint's url, events, shops or status (prints the request; --yes sends)", update,
        [
            Flag("--url", "new HTTPS receiver", metavar="URL"),
            _TYPES_FLAG,
            Flag("--shop", "new shop list, replaces the old one; repeat or comma-separate",
                 kind="multi", default=[], metavar="SHOP_ID"),
            Flag("--status", "pause or resume delivery", choices=STATUSES, metavar="ACTIVE|PAUSED"),
        ],
        "boost webhook update <ENDPOINT_ID> --status ACTIVE --yes",
    ),
    _endpoint_cmd(
        "webhook rotate-secret", "Issue a new signing secret; the old one stays valid for 24h", rotate_secret, [],
        "boost webhook rotate-secret <ENDPOINT_ID> --yes",
    ),
    _endpoint_cmd(
        "webhook test", "Push a webhook.test event to an endpoint", test, [],
        "boost webhook test <ENDPOINT_ID> --yes",
    ),
    _endpoint_cmd(
        "webhook replay", "Push past events (last 30 days) to an endpoint again", replay,
        [
            Flag("--from", "events that occurred since: 24h | 7d | yyyy-MM-dd | ISO", metavar="WHEN"),
            Flag("--to", "until, exclusive (default now)", metavar="WHEN"),
            _TYPES_FLAG,
        ],
        "boost webhook replay <ENDPOINT_ID> --from 24h --yes",
    ),
]
