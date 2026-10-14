"""Shared flags and helpers: shop resolution, time windows, cursor paging, writes, output."""

from __future__ import annotations

import datetime
import json
import re
import shlex
import uuid
from pathlib import Path

from .. import api, render
from ..core import Flag
from ..errors import BoostError, UsageError

REGIONS = (
    "US", "ID", "VN", "TH", "MY", "PH", "MX", "BR", "GB",
    "DE", "ES", "SG", "FR", "JP", "IT", "NL", "IE", "PL",
)
EVENT_TYPES = ("outreach.task.updated", "outreach.recipient.updated", "collaboration.updated", "sample.updated")
PAGE_MAX = 100
ALL_MAX_PAGES = 20  # --all safety cap: 20 pages x 100 rows

_RELATIVE = re.compile(r"^(\d+)([mhd])$")
_UNITS = {"m": "minutes", "h": "hours", "d": "days"}


# --- flags -------------------------------------------------------------------

def shop_flag() -> Flag:
    return Flag("--shop", "Kaloboost shop_id (from `boost shops`; default: config boost_shop)", metavar="SHOP_ID")


def region_flag() -> Flag:
    return Flag("--region", "creator market: " + " ".join(REGIONS), default="US", metavar="REGION")


def page_flags(default_limit: int = 20, max_pages: int = ALL_MAX_PAGES) -> list[Flag]:
    return [
        Flag("--limit", f"rows per page (1-{PAGE_MAX})", kind="int", default=default_limit),
        Flag("--cursor", "continue from a previous page's next_cursor", metavar="CURSOR"),
        Flag("--all", f"follow next_cursor automatically (up to {max_pages} pages)", kind="flag", default=False),
    ]


def since_flag(what: str = "updated") -> Flag:
    return Flag(
        "--since",
        f"only rows {what} since: 30m | 24h | 7d | yyyy-MM-dd | ISO 8601 UTC",
        metavar="WHEN",
    )


def file_flag(what: str) -> Flag:
    return Flag("--file", f"read {what} from a file, one per line (# comments ok); adds to the arguments", metavar="PATH")


def yes_flag() -> Flag:
    return Flag("--yes", "really send it; without --yes the request is only printed, nothing is sent", kind="flag", default=False)


def key_flag() -> Flag:
    return Flag(
        "--idempotency-key",
        "retry an earlier attempt with its key so it can't run twice (default: a new UUID)",
        metavar="KEY",
    )


# --- argument helpers --------------------------------------------------------

def shop(cfg, opts) -> str:
    value = (opts.get("shop") or cfg.shop or "").strip()
    if not value:
        raise UsageError(
            "--shop is required",
            ["Run `boost shops` for shop ids, or save a default: `boost config set --shop <SHOP_ID>`"],
        )
    return value


def region(opts) -> str:
    value = (opts.get("region") or "US").upper()
    if value not in REGIONS:
        raise UsageError(f"unknown region '{value}'", [f"valid regions: {' '.join(REGIONS)}"])
    return value


def limit(opts) -> int:
    value = int(opts.get("limit") or 20)
    if not 1 <= value <= PAGE_MAX:
        raise UsageError(f"--limit must be 1-{PAGE_MAX}, got {value}")
    return value


def iso(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_when(value: str | None, flag: str = "--since", *, now: datetime.datetime | None = None) -> str | None:
    """`7d` / `24h` / `30m` / `yyyy-MM-dd` / ISO 8601 -> ISO 8601 UTC with second precision."""
    if not value:
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    v = value.strip()
    m = _RELATIVE.match(v)
    if m:
        return iso(now - datetime.timedelta(**{_UNITS[m.group(2)]: int(m.group(1))}))
    try:
        if len(v) == 10:
            d = datetime.date.fromisoformat(v)
            return iso(datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc))
        dt = datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise UsageError(
            f"invalid {flag} '{value}'",
            ["expected 30m | 24h | 7d | yyyy-MM-dd | ISO 8601 such as 2026-09-01T00:00:00Z"],
        ) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return iso(dt)


def parse_future(value: str | None, flag: str, *, now: datetime.datetime | None = None) -> str | None:
    """Like parse_when, but `30m` / `24h` / `7d` count forward from now."""
    if not value:
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    m = _RELATIVE.match(value.strip())
    if m:
        return iso(now + datetime.timedelta(**{_UNITS[m.group(2)]: int(m.group(1))}))
    try:
        return parse_when(value, flag, now=now)
    except UsageError:
        raise UsageError(
            f"invalid {flag} '{value}'",
            ["expected 30m | 24h | 7d (from now) | yyyy-MM-dd | ISO 8601 such as 2026-12-01T00:00:00Z"],
        ) from None


def ids(values: list[str], noun: str, cap: int | None = None) -> list[str]:
    out: list[str] = []
    for v in values:
        out.extend(p.strip() for p in v.split(",") if p.strip())
    if not out:
        raise UsageError(f"no {noun} given")
    if cap and len(out) > cap:
        raise UsageError(f"at most {cap} {noun}s per call, got {len(out)}")
    return out


def inputs(args: list[str], opts, noun: str, cap: int) -> list[str]:
    """Positional values plus `--file` lines, comma-split, order kept."""
    values = list(args)
    path = opts.get("file")
    if path:
        try:
            text = Path(path).expanduser().read_text(encoding="utf-8")
        except OSError as e:
            raise UsageError(f"cannot read --file {path}: {e.strerror or e}") from None
        values += [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    return ids(values, noun, cap)


def event_types(value: str | None) -> list[str] | None:
    if not value:
        return None
    types = ids([value], "event type")
    bad = [t for t in types if t not in EVENT_TYPES]
    if bad:
        raise UsageError(f"unsupported event type(s): {', '.join(bad)}", [f"v1 types: {', '.join(EVENT_TYPES)}"])
    return types


# --- writes ------------------------------------------------------------------

def send(
    cfg, opts, method: str, path: str, *,
    params: dict | None = None,
    body: dict | None = None,
    key: str | None = None,
    retry_hint: str | None = None,
    confirm: bool = True,
    confirm_flags: str = "--yes",
) -> dict | None:
    """Run a write call with an Idempotency-Key; without --yes print it instead (returns None).

    The key is reused across the client's automatic retries, and surfaced when
    the outcome is unknown (network / 5xx / in-progress) so the caller can retry
    the same operation without running it twice.
    """
    key = key or opts.get("idempotency_key") or str(uuid.uuid4())
    retry_hint = retry_hint or f"--idempotency-key {key}"
    query = {k: v for k, v in (params or {}).items() if v is not None}
    if confirm and not opts.get("yes"):
        preview: dict = {"method": method, "path": path}
        if query:
            preview["query"] = query
        preview["idempotency_key"] = key
        if body is not None:
            preview["body"] = body
        if opts.get("json"):
            dump_json({"dry_run": preview})
        else:
            render.emit_detail("dry_run", preview)
            render.emit_help([
                f"Nothing was sent. Show this to the user; once they confirm, run the same command with {confirm_flags}",
            ])
        return None
    try:
        return api.request(cfg, method, path, params=query, body=body, headers={"Idempotency-Key": key})
    except BoostError as e:
        if e.kind == "network" or "IN_PROGRESS" in str(e):
            e.help_lines.append(f"The outcome is unknown — retry the identical command with {retry_hint} so it runs at most once")
        raise


# --- paging ------------------------------------------------------------------

def fetch_pages(
    cfg, path: str, params: dict, opts, *,
    stop_on_empty: bool = False, stream: bool = False, max_pages: int = ALL_MAX_PAGES,
):
    """One page, or every page with --all. Returns (rows, next_cursor, pages_read).

    `stop_on_empty` is for incremental streams (/samples) whose last page is an
    empty `data` rather than a null cursor. A page can legitimately be empty while
    still carrying a cursor (/collaborations hits a server-side time budget), so
    without that flag only a null cursor ends the loop. `stream` is for /events,
    which always hands back a cursor to poll with later: `has_more` ends the loop.
    """
    params = dict(params, limit=limit(opts))
    cursor = opts.get("cursor")
    rows: list = []
    pages = 0
    while True:
        env = api.request(cfg, "GET", path, params=dict(params, cursor=cursor))
        data = env.get("data")
        batch = data if isinstance(data, list) else []
        rows.extend(batch)
        pages += 1
        page = env.get("page") or {}
        cursor = page.get("next_cursor")
        if not opts.get("all") or not cursor or (stop_on_empty and not batch):
            break
        if stream and not page.get("has_more"):
            break
        if pages >= max_pages:
            break
    if stop_on_empty and not rows:
        cursor = None  # caught up; nothing new to continue from
    return rows, cursor, pages


def dedupe_latest(rows: list[dict], key: str, ts: str = "updated_at") -> list[dict]:
    """Keep one row per `key`: the later `ts`, ties go to the later occurrence."""
    best: dict = {}
    order: list = []
    for r in rows:
        k = r.get(key)
        if k is None:
            order.append(r)
            continue
        if k not in best:
            order.append(k)
            best[k] = r
        elif str(r.get(ts) or "") >= str(best[k].get(ts) or ""):
            best[k] = r
    return [best[x] if not isinstance(x, dict) else x for x in order]


def again(path: str, *parts) -> str:
    """Rebuild a command line for a continuation hint (cursor appended by caller)."""
    out = ["boost", path]
    for p in parts:
        if p is None or p is False:
            continue
        out.append(p if isinstance(p, str) and p.startswith("--") else shlex.quote(str(p)))
    return " ".join(out)


def flag_pairs(**kv) -> list:
    """{'shop': 'x', 'since': None} -> ['--shop', 'x'] (None values dropped)."""
    out: list = []
    for k, v in kv.items():
        if v is not None:
            out += ["--" + k.replace("_", "-"), v]
    return out


def page_hints(
    rows: list, cursor: str | None, pages: int, base_cmd: str, opts, extra: list[str] | None = None,
    max_pages: int = ALL_MAX_PAGES,
) -> list[str]:
    hints = list(extra or [])
    if cursor:
        if opts.get("all") and pages >= max_pages:
            hints.append(f"Stopped after {pages} pages; continue with `{base_cmd} --all --cursor {cursor}`")
        else:
            hints.append(f"More: `{base_cmd} --cursor {cursor}` (or add --all)")
    return hints


# --- output ------------------------------------------------------------------

def dump_json(value) -> None:
    render.out(json.dumps(value, ensure_ascii=False))


def joined(values, sep: str = "|"):
    if not values:
        return None
    return sep.join(str(v) for v in values)


def money(obj) -> str | None:
    if not isinstance(obj, dict) or obj.get("amount") is None:
        return None
    return f"{obj['amount']} {obj.get('currency') or ''}".strip()
