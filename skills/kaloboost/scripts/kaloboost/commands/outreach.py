"""`boost outreach` — outreach tasks (TikTok DM / target invitations) and per-creator results."""

from __future__ import annotations

import urllib.parse

from .. import api, render
from ..core import Command, Flag
from ..errors import UsageError
from . import common

METHODS = ("TIKTOK_DM", "TIKTOK_TARGET_COLLABORATION")
OPEN_STATUSES = {"ACCEPTED", "QUEUED", "SCHEDULED", "RUNNING", "PAUSED"}

TASK_FIELDS = (
    "outreach_task_id", "task_name", "method", "type", "status",
    "total", "sent_ok", "sent_fail", "created_at", "updated_at",
)


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _task_row(t: dict) -> dict:
    return {
        "outreach_task_id": t.get("outreach_task_id"),
        "task_name": render.clip(t.get("task_name")),
        "method": t.get("outreach_method"),
        "type": t.get("task_type"),
        "status": t.get("status"),
        "total": t.get("total_count"),
        "sent_ok": t.get("send_success_count"),
        "sent_fail": t.get("send_fail_count"),
        "created_at": t.get("created_at"),
        "updated_at": t.get("updated_at"),
    }


def task_list(cfg, opts, args):
    shop = common.shop(cfg, opts)
    since = common.parse_when(opts.get("since"))
    rows, cursor, pages = common.fetch_pages(
        cfg, "/outreach-tasks", {"shop_id": shop, "updated_from": since}, opts
    )
    if opts.get("all"):
        rows = common.dedupe_latest(rows, "outreach_task_id")
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": cursor})
        return 0
    ctx = f"shop {shop}" + (f", updated since {since}" if since else "")
    if not rows:
        render.emit_empty("outreach_tasks", ctx, ["Tasks created in Kaloboost or via the API both show here"])
        return 0
    render.emit_table("outreach_tasks", [_task_row(t) for t in rows], TASK_FIELDS)
    hints = [
        f"Run `boost outreach recipients <outreach_task_id> --shop {shop}` for per-creator send results",
        "total - sent_ok - sent_fail = not sent yet or canceled, not failures",
    ]
    if since:
        hints.append("With --since, unfinished tasks (ACCEPTED/QUEUED/SCHEDULED/RUNNING/PAUSED) are always included")
    base = common.again("outreach list", *common.flag_pairs(shop=shop, since=since))
    render.emit_help(common.page_hints(rows, cursor, pages, base, opts, hints))
    return 0


def task_get(cfg, opts, args):
    shop = common.shop(cfg, opts)
    data = api.request(cfg, "GET", f"/outreach-tasks/{_q(args[0])}", params={"shop_id": shop}).get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("outreach_task", data)
    hints = [f"Per-creator results: `boost outreach recipients {args[0]} --shop {shop}`"]
    if data.get("task_type") == "AUTOMATION":
        hints.append("AUTOMATION tasks may never finish — counts keep growing while the rule is on")
    render.emit_help(hints)
    return 0


def recipients(cfg, opts, args):
    shop = common.shop(cfg, opts)
    task = args[0]
    rows, cursor, pages = common.fetch_pages(
        cfg, f"/outreach-tasks/{_q(task)}/recipients", {"shop_id": shop}, opts
    )
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": cursor})
        return 0
    if not rows:
        render.emit_empty("recipients", f"task {task}, shop {shop}")
        return 0
    display = [
        {
            "creator_oecuid": r.get("creator_oecuid"),
            "outreach_status": r.get("outreach_status"),
            "send_status": r.get("send_status"),
            "error": r.get("error_code"),
            "error_description": render.clip(r.get("error_description"), 60),
            "send_time": r.get("send_time"),
        }
        for r in rows
    ]
    render.emit_table(
        "recipients", display,
        ("creator_oecuid", "outreach_status", "send_status", "error", "error_description", "send_time"),
    )
    tally: dict = {}
    for r in rows:
        tally[r.get("send_status")] = tally.get(r.get("send_status"), 0) + 1
    hints = [
        "this page: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1])),
        "Creator profile: `boost creator get <creator_oecuid> --region <shop region>`",
    ]
    base = common.again("outreach recipients", task, *common.flag_pairs(shop=shop))
    render.emit_help(common.page_hints(rows, cursor, pages, base, opts, hints))
    return 0


def templates(cfg, opts, args):
    shop = common.shop(cfg, opts)
    operator = (opts.get("operator") or "").strip()
    if not operator:
        raise UsageError(
            "--operator is required (the Kaloboost member's login email or phone)",
            ["Templates belong to a member: e.g. --operator member@example.com or --operator '+86 13800000000'"],
        )
    method = opts.get("method")
    ttype = opts.get("type")
    if ttype and method == "TIKTOK_DM":
        raise UsageError("--type only applies to --method TIKTOK_TARGET_COLLABORATION")
    params = {"shop_id": shop, "operator_account": operator, "outreach_method": method, "template_type": ttype}
    rows, cursor, pages = common.fetch_pages(cfg, "/outreach-templates", params, opts)
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": cursor})
        return 0
    if not rows:
        render.emit_empty("templates", f"{operator}, {method}, shop {shop}", ["Templates are created by the member in the Kaloboost console"])
        return 0
    display = []
    for r in rows:
        segs = ((r.get("dm") or {}).get("segments") or [])
        first_text = next((s.get("text") for s in segs if isinstance(s, dict) and s.get("text")), None)
        inv = r.get("invitation") or {}
        display.append(
            {
                "template_id": r.get("template_id"),
                "template_name": render.clip(r.get("template_name")),
                "type": r.get("template_type"),
                "preview": render.clip(first_text or inv.get("invite_message") or inv.get("invite_name"), 60),
                "products": len(r.get("products") or []) or None,
                "updated_at": r.get("updated_at"),
            }
        )
    render.emit_table("templates", display, ("template_id", "template_name", "type", "preview", "products", "updated_at"))
    base = common.again(
        "outreach templates",
        *common.flag_pairs(shop=shop, operator=operator, method=method, type=ttype),
    )
    render.emit_help(common.page_hints(rows, cursor, pages, base, opts, ["Add --json for full template content"]))
    return 0


COMMANDS = [
    Command(
        path="outreach list",
        summary="Outreach tasks of a shop with send progress (newest-created last)",
        handler=task_list,
        flags=[common.shop_flag(), common.since_flag(), *common.page_flags()],
        examples=["boost outreach list --shop <SHOP_ID>", "boost outreach list --shop <SHOP_ID> --since 7d --all"],
    ),
    Command(
        path="outreach get",
        summary="One outreach task: schedule, invitation products and commission, send counts",
        handler=task_get,
        flags=[common.shop_flag()],
        positional="outreach_task_id",
        pos_min=1,
        pos_max=1,
        examples=["boost outreach get <TASK_ID> --shop <SHOP_ID>"],
    ),
    Command(
        path="outreach recipients",
        summary="Per-creator results of an outreach task (sent / failed / queued, with reasons)",
        handler=recipients,
        flags=[common.shop_flag(), *common.page_flags(default_limit=50)],
        positional="outreach_task_id",
        pos_min=1,
        pos_max=1,
        examples=["boost outreach recipients <TASK_ID> --shop <SHOP_ID> --all"],
    ),
    Command(
        path="outreach templates",
        summary="Message / invitation templates a Kaloboost member can use in a shop's market",
        handler=templates,
        flags=[
            common.shop_flag(),
            Flag("--operator", "member account: login email or '+CC NUMBER'", metavar="ACCOUNT"),
            Flag("--method", "channel", default="TIKTOK_DM", choices=METHODS, metavar="|".join(METHODS)),
            Flag(
                "--type", "invitation template type (target invitations only)",
                choices=("INVITE_CONTENT", "INVITE_PRODUCT"), metavar="INVITE_CONTENT|INVITE_PRODUCT",
            ),
            *common.page_flags(default_limit=50),
        ],
        examples=["boost outreach templates --shop <SHOP_ID> --operator member@example.com --method TIKTOK_DM"],
    ),
]
