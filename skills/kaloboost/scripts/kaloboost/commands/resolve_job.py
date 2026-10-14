"""`boost resolve-job` — async creator identity resolution for up to 10,000 handles / user ids."""

from __future__ import annotations

import urllib.parse

from .. import api, render
from ..core import Command
from . import common
from .creator import JOB_MAX, RESOLVE_FIELDS, resolve_hints, resolve_items, resolve_rows

OPEN_STATUSES = {"QUEUED", "RUNNING"}
RESULT_PAGES = JOB_MAX // common.PAGE_MAX  # --all reads a whole job


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def create(cfg, opts, args):
    region = common.region(opts)
    items = resolve_items(args, opts, region, JOB_MAX)
    env = common.send(cfg, opts, "POST", "/identity-resolution-jobs", body={"items": items}, confirm=False)
    data = env.get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("resolve_job", data)
    job = data.get("job_id")
    render.emit_help([
        f"Poll every few seconds: `boost resolve-job get {job}`; then `boost resolve-job results {job} --all`",
        "At most 2 jobs run at once per key — wait for one to finish before starting another",
    ])
    return 0


def get(cfg, opts, args):
    data = api.request(cfg, "GET", f"/identity-resolution-jobs/{_q(args[0])}").get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("resolve_job", data)
    if data.get("status") in OPEN_STATUSES:
        hint = f"Still {data.get('status')} — check again in a few seconds"
    else:
        hint = f"Results: `boost resolve-job results {args[0]} --all`"
    render.emit_help([hint])
    return 0


def results(cfg, opts, args):
    job = args[0]
    rows, cursor, pages = common.fetch_pages(
        cfg, f"/identity-resolution-jobs/{_q(job)}/results", {}, opts, max_pages=RESULT_PAGES
    )
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": cursor})
        return 0
    base = common.again("resolve-job results", job)
    if not rows:
        render.emit_empty("creators", f"job {job}", common.page_hints(rows, cursor, pages, base, opts, [
            f"A job still QUEUED/RUNNING has no results yet: `boost resolve-job get {job}`",
        ]))
        return 0
    render.emit_table("creators", resolve_rows(rows), RESOLVE_FIELDS)
    tally: dict = {}
    for r in rows:
        tally[r.get("status")] = tally.get(r.get("status"), 0) + 1
    hints = ["this page: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1]))]
    hints += resolve_hints(rows, None)
    render.emit_help(common.page_hints(rows, cursor, pages, base, opts, hints, RESULT_PAGES))
    return 0


COMMANDS = [
    Command(
        path="resolve-job create",
        summary=f"Start an async resolve of up to {JOB_MAX} handles / user ids (bigger batches than `creator resolve`)",
        handler=create,
        flags=[common.region_flag(), common.file_flag("handles / user ids"), common.key_flag()],
        positional="@handle|user_id",
        pos_min=0,
        pos_max=None,
        examples=["boost resolve-job create --file handles.txt --region US"],
    ),
    Command(
        path="resolve-job get",
        summary="Status and match counts of a resolve job",
        handler=get,
        positional="job_id",
        pos_min=1,
        pos_max=1,
        examples=["boost resolve-job get <JOB_ID>"],
    ),
    Command(
        path="resolve-job results",
        summary="Per-creator results of a resolve job (same rows as `creator resolve`)",
        handler=results,
        flags=common.page_flags(default_limit=100, max_pages=RESULT_PAGES),
        positional="job_id",
        pos_min=1,
        pos_max=1,
        examples=["boost resolve-job results <JOB_ID> --all"],
    ),
]
