"""Shared flags and helpers: shop resolution, time windows, cursor paging, output."""

from __future__ import annotations

import datetime
import json
import re
import shlex

from .. import api, render
from ..core import Flag
from ..errors import UsageError

REGIONS = (
    "US", "ID", "VN", "TH", "MY", "PH", "MX", "BR", "GB",
    "DE", "ES", "SG", "FR", "JP", "IT", "NL", "IE", "PL",
)
PAGE_MAX = 100
ALL_MAX_PAGES = 20  # --all safety cap: 20 pages x 100 rows

_RELATIVE = re.compile(r"^(\d+)([mhd])$")
_UNITS = {"m": "minutes", "h": "hours", "d": "days"}


# --- flags -------------------------------------------------------------------

def shop_flag() -> Flag:
    return Flag("--shop", "Kaloboost shop_id (from `boost shops`; default: config boost_shop)", metavar="SHOP_ID")


def region_flag() -> Flag:
    return Flag("--region", "creator market: " + " ".join(REGIONS), default="US", metavar="REGION")


def page_flags(default_limit: int = 20) -> list[Flag]:
    return [
        Flag("--limit", f"rows per page (1-{PAGE_MAX})", kind="int", default=default_limit),
        Flag("--cursor", "continue from a previous page's next_cursor", metavar="CURSOR"),
        Flag("--all", f"follow next_cursor automatically (up to {ALL_MAX_PAGES} pages)", kind="flag", default=False),
    ]


def since_flag(what: str = "updated") -> Flag:
    return Flag(
        "--since",
        f"only rows {what} since: 30m | 24h | 7d | yyyy-MM-dd | ISO 8601 UTC",
        metavar="WHEN",
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


def ids(values: list[str], noun: str, cap: int | None = None) -> list[str]:
    out: list[str] = []
    for v in values:
        out.extend(p.strip() for p in v.split(",") if p.strip())
    if not out:
        raise UsageError(f"no {noun} given")
    if cap and len(out) > cap:
        raise UsageError(f"at most {cap} {noun}s per call, got {len(out)}")
    return out


# --- paging ------------------------------------------------------------------

def fetch_pages(cfg, path: str, params: dict, opts, *, stop_on_empty: bool = False, stream: bool = False):
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
        if pages >= ALL_MAX_PAGES:
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


def page_hints(rows: list, cursor: str | None, pages: int, base_cmd: str, opts, extra: list[str] | None = None) -> list[str]:
    hints = list(extra or [])
    if cursor:
        if opts.get("all") and pages >= ALL_MAX_PAGES:
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
