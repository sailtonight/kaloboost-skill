"""Content for the no-args home view.

The SKILL.md next to this package mirrors this command table — keep both
in sync when commands change.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from . import __version__, onboarding, toon
from .config import DEFAULT_BASE_URL, Config

DESCRIPTION = (
    "Kaloboost creator-outreach data for TikTok Shop sellers — bound shops, creator lookup, "
    "outreach tasks, collaborations, free samples, affiliate orders, change events"
)

# (command, what) — the `what` column is deliberately terse; details live in --help
COMMAND_TABLE = [
    ("boost capabilities", "which features are open for this key; creator regions; rate limits"),
    ("boost shops", "bound shops → shop_id for --shop; per-shop capabilities"),
    ("boost creator resolve <@handle|user_id...>", "TikTok creator → creator_oecuid; --region"),
    ("boost creator get <creator_oecuid...>", "profile, contact email/phone, followers, GMV band; --region"),
    ("boost outreach list", "outreach tasks + send progress; --since"),
    ("boost outreach get <task_id>", "schedule, invitation products, commission"),
    ("boost outreach recipients <task_id>", "per-creator send result and failure reason"),
    ("boost outreach templates", "a member's DM / invitation templates; --operator --method"),
    ("boost collab list", "collaboration records: cooperate_status, outreach_result; --since"),
    ("boost collab get <id>", "one collaboration record"),
    ("boost sample list", "sample requests: status, product, commission, content counts; --since --status"),
    ("boost sample get <id>", "SKUs, fulfillment, status timeline"),
    ("boost sample contents <id>", "videos/lives posted for a sample: views, likes, orders"),
    ("boost order list", "affiliate orders by order time; --from --to (≤90 days)"),
    ("boost event list", "change events (outreach, collab, sample); --types --since"),
    ("boost config", "show/set key (shared with kalo), default shop, endpoint"),
]

CONVENTIONS = [
    "Shop-level commands need --shop <shop_id> from `boost shops` (or `boost config set --shop`)",
    "Lists take --limit (1-100) --cursor --all; follow the `More:` hint to page, it repeats the needed flags",
    "--since/--from/--to take 30m | 24h | 7d | yyyy-MM-dd | ISO 8601 UTC",
    "Creator commands are per market: --region US (default) GB ID TH VN PH MY SG JP MX BR DE ES FR IT NL IE PL",
    "Run `boost <command> --help` for per-command flags and examples",
]


def bin_path() -> str:
    found = shutil.which("boost")
    path = found or sys.argv[0] or "boost"
    home = str(Path.home())
    if path.startswith(home):
        path = "~" + path[len(home):]
    return path


def auth_line(cfg: Config) -> str:
    if cfg.authed:
        return f"auth: ok (key …{cfg.api_key[-4:]})" if len(cfg.api_key) > 4 else "auth: ok"
    return "auth: not configured — no query will run until a key is set (see setup below)"


def home_text(cfg: Config) -> str:
    lines = [
        f"bin: {bin_path()} (boost {__version__})",
        f"description: {DESCRIPTION}",
        auth_line(cfg),
    ]
    env = "" if cfg.base_url == DEFAULT_BASE_URL else f" · endpoint {cfg.base_url}"
    lines.append(f"defaults: shop {cfg.shop or '(none — pass --shop)'}{env}")
    if not cfg.authed:
        lines.append("")
        lines.append(f"setup[{len(onboarding.SETUP_LINES)}]:")
        lines.extend(f"  {ln}" for ln in onboarding.SETUP_LINES)
    lines += [
        "",
        toon.tabular("commands", [{"command": c, "what": w} for c, w in COMMAND_TABLE], ["command", "what"]),
        "",
        f"help[{len(CONVENTIONS)}]:",
    ]
    lines.extend(f"  {c}" for c in CONVENTIONS)
    return "\n".join(lines)
