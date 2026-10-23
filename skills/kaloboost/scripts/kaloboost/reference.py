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
    "Kaloboost creator outreach for TikTok Shop sellers — shops, creator lookup, outreach tasks "
    "(read, send, cancel), creator chat, collaborations, samples, content, affiliate orders, change events, webhooks"
)

# (command, what) — the `what` column is deliberately terse; details live in --help
COMMAND_TABLE = [
    ("boost capabilities", "which features are open for this key; creator regions; rate limits"),
    ("boost shops", "bound shops → shop_id for --shop; per-shop capabilities"),
    ("boost creator resolve <@handle|user_id...>", "TikTok creator → creator_oecuid (≤100); --region"),
    ("boost creator get <creator_oecuid...>", "profile, contact email/phone, followers, GMV band; --region"),
    ("boost creator changes", "creators of a region whose profile or metrics changed; --since"),
    ("boost resolve-job create|get|results", "async resolve of up to 10,000 handles / user ids"),
    ("boost outreach list", "outreach tasks + send progress; --since"),
    ("boost outreach get <task_id>", "schedule, invitation products, commission"),
    ("boost outreach recipients <task_id>", "per-creator send result and failure reason"),
    ("boost outreach templates", "DM / invitation templates; --method"),
    ("boost outreach products", "products usable in a DM card / invitation (selectable); --method"),
    ("boost outreach upload-image <path>", "JPG/PNG → image_id for DM image segments"),
    ("boost outreach create <creator_oecuid...>", "send a DM / target invitation, content inline or template [write, --yes]"),
    ("boost outreach create-template", "save a DM / invitation template in Kaloboost [write, --yes]"),
    ("boost outreach cancel <task_id>", "stop what is not sent yet [write, --yes]"),
    ("boost chat list", "chat conversations with creators, unread counts; --status UNREAD|UNREPLIED|…"),
    ("boost chat messages <conversation_id>", "messages of a conversation, sender role"),
    ("boost chat open <creator_oecuid>", "get or start the conversation with a creator → conversation_id"),
    ("boost chat send <conversation_id>", "reply: text, image, product / invitation / sample card [write, --yes]"),
    ("boost chat upload-image <path>", "JPG/PNG/GIF/WebP → url, width, height for chat images"),
    ("boost chat read|status|counts", "mark read, star/archive, unread/unreplied counts"),
    ("boost collab list", "collaboration records: cooperate_status, outreach_result; --since"),
    ("boost collab get <id>", "one collaboration record"),
    ("boost sample list", "sample requests: status, product, commission, content counts; --since --status"),
    ("boost sample get <id>", "SKUs, fulfillment, status timeline"),
    ("boost sample contents <id>", "videos/lives posted for a sample: views, likes, orders"),
    ("boost content list", "creator videos/lives of a shop with metrics; --creator --published-from"),
    ("boost content get <id>", "one video/live: sample & collaboration links, metrics"),
    ("boost order list", "affiliate orders by order time; --from --to (≤90 days)"),
    ("boost attribution list", "affiliate attribution per order line; --creator --order --since"),
    ("boost attribution get <id>", "one attribution record: amounts, settlement"),
    ("boost event list", "change events (outreach, collab, sample, chat message); --types --since"),
    ("boost webhook list", "push endpoints for change events"),
    ("boost webhook create|update|rotate-secret|test|replay", "manage push endpoints [write, --yes]"),
    ("boost config", "show/set key (shared with kalo), default shop, endpoint"),
]

CONVENTIONS = [
    "Shop-level commands need --shop <shop_id> from `boost shops` (or `boost config set --shop`)",
    "Lists take --limit (1-100) --cursor --all; follow the `More:` hint to page, it repeats the needed flags",
    "--since/--from/--to take 30m | 24h | 7d | yyyy-MM-dd | ISO 8601 UTC",
    "Creator commands are per market: --region US (default) GB ID TH VN PH MY SG JP MX BR DE ES FR IT NL IE PL",
    "[write] commands only print the request; add --yes to send it after the user confirms",
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
