"""`boost outreach` — outreach tasks (TikTok DM / target invitations) and per-creator results."""

from __future__ import annotations

import base64
import datetime
import decimal
import json
import re
import secrets
import time
import urllib.parse
from pathlib import Path

from .. import api, render
from ..core import Command, Flag
from ..errors import BoostError, UsageError
from . import common

METHODS = ("TIKTOK_DM", "TIKTOK_TARGET_COLLABORATION")
RECIPIENT_MAX = 10000  # /capabilities limits.outreach_recipient_limit, a v1 contract constant
# Big tasks are built synchronously: 15-80s, sometimes 2-3 min; a timed-out attempt keeps building
# server-side and answers 409 IN_PROGRESS to same-key retries for up to 390s.
CREATE_TIMEOUT = 210.0
IN_PROGRESS_WAIT = 20.0
IN_PROGRESS_DEADLINE = 400.0
PRODUCT_MAX = 100
CONTACT_TYPES = ("WHATSAPP", "EMAIL", "LINE", "ZALO", "VIBER", "FACEBOOK", "TELEGRAM", "PHONE")
NO_COUNTRY = ("EMAIL", "FACEBOOK")
COOPERATION = ("DELIVERY_VIDEO", "DELIVERY_LIVE", "NONE")
DEDUP = ("NONE", "DAYS_7", "DAYS_15", "DAYS_30", "DAYS_60", "DAYS_90")
IMAGE_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_EXPIRE = datetime.timedelta(days=7)

# Flags that make up inline content, by where they go.
DM_KEYS = ("text", "image", "card")
INVITE_KEYS = ("invite_name", "invite_message", "contact", "cooperation", "no_sample", "sample_review", "sync_dm", "sync_dedup")
PRODUCT_KEYS = ("commission", "ads_commission")

# The only creator placeholder: ${handle}. The two legacy console spellings are accepted too.
_PLACEHOLDER = re.compile(r"\$\{[^}]*\}|\{\{[^}]*\}\}|\{[^{}]*\}|\$[A-Za-z_]\w*")
_ALLOWED_PLACEHOLDERS = {"${handle}", "{{creators username}}", "{{user_name}}"}
OPEN_STATUSES = {"ACCEPTED", "QUEUED", "SCHEDULED", "RUNNING", "PAUSED"}

RECIPIENT_ERROR_HINTS = {
    "TARGET_INVITATION_UNAVAILABLE_CREATOR": "TARGET_INVITATION_UNAVAILABLE_CREATOR: TikTok doesn't let this creator "
    "receive target invitations — sending again won't help; ask the user for other creators",
    "CREATOR_OPENID_NOT_RETRIEVED": "CREATOR_OPENID_NOT_RETRIEVED: TikTok couldn't identify this creator for the shop — "
    "skip them or try later",
    "TARGET_INVITATION_QUOTA_LIMIT": "TARGET_INVITATION_QUOTA_LIMIT: the shop's invitation quota is used up — "
    "it refills later; send to fewer creators or wait",
}

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
    errors = {r.get("error_code") for r in rows}
    hints += [hint for code, hint in RECIPIENT_ERROR_HINTS.items() if code in errors]
    base = common.again("outreach recipients", task, *common.flag_pairs(shop=shop))
    render.emit_help(common.page_hints(rows, cursor, pages, base, opts, hints))
    return 0


def _operator(opts) -> str | None:
    """--operator, or None: the server then runs the call as the key's own account."""
    return (opts.get("operator") or "").strip() or None


def _external_id() -> str:
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"boost-{now}-{secrets.token_hex(4)}"


def _given(opts, keys) -> list[str]:
    return ["--" + k.replace("_", "-") for k in keys if opts.get(k)]


def _check_text(flag: str, text: str, *, placeholders: bool = True) -> str:
    if not text.strip():
        raise UsageError(f"{flag} is empty")
    if placeholders and "@${handle}" in text:
        raise UsageError(
            f"{flag}: drop the @ before ${{handle}}",
            ["${handle} becomes the creator's username without @ — `Hi ${handle}!` reaches alice_shop as `Hi alice_shop!`"],
        )
    for m in _PLACEHOLDER.finditer(text):
        token = m.group(0)
        if not placeholders or token not in _ALLOWED_PLACEHOLDERS:
            hint = ("The invite name can't hold a placeholder" if not placeholders
                    else "The only creator placeholder is ${handle} (the creator's TikTok username, no @)")
            raise UsageError(f"{flag}: unsupported placeholder {token}", [hint])
    return text


def _ratio(value: str, flag: str) -> str:
    raw = str(value).strip()
    try:
        d = decimal.Decimal(raw)
    except decimal.InvalidOperation:
        raise UsageError(f"{flag} '{raw}' is not a ratio", ["Commission is a ratio: 15% is 0.15"]) from None
    if not (decimal.Decimal("0.01") <= d <= decimal.Decimal("0.80")) or d.as_tuple().exponent < -4:
        raise UsageError(f"{flag} '{raw}' must be 0.01-0.80 with at most 4 decimals", ["Commission is a ratio: 15% is 0.15"])
    return raw


def _contact(raw: str) -> dict:
    kind, _, rest = raw.partition(":")
    kind = kind.strip().upper()
    if kind not in CONTACT_TYPES or not rest.strip():
        raise UsageError(
            f"invalid --contact '{raw}'",
            [f"Use TYPE:VALUE[:CC] with TYPE one of {', '.join(CONTACT_TYPES)}, e.g. WHATSAPP:812345678:TH or EMAIL:hi@shop.com"],
        )
    value, country = rest.strip(), None
    m = re.match(r"^(.*):([A-Za-z]{2})$", value)
    if m and kind not in NO_COUNTRY:
        value, country = m.group(1).strip(), m.group(2).upper()
    if "REPLACE_WITH" in value.upper() or re.search(r"@example\.(com|org)$", value, re.I):
        raise UsageError("--contact is a placeholder", ["Ask the user for the merchant's real contact — never make one up"])
    c = {"type": kind, "value": value}
    if country:
        c["country_code"] = country
    return c


def _dm(opts) -> dict:
    texts = [_check_text(f"--text #{i + 1}", t) for i, t in enumerate(opts.get("text") or [])]
    images = [i.strip() for i in opts.get("image") or [] if i.strip()]
    cards = [c.strip() for c in opts.get("card") or [] if c.strip()]
    if not texts:
        raise UsageError("a DM needs at least one --text", ["e.g. --text 'Hi ${handle}! We love your videos.' (single quotes, or the shell eats ${handle})"])
    if len(images) > 3 or len(texts) + len(images) + len(cards) > 5:
        raise UsageError("a DM takes at most 5 segments (--text, --image, --card together), at most 3 --image")
    return {
        "segments": [{"type": "TEXT", "text": t} for t in texts]
        + [{"type": "IMAGE", "image_id": i} for i in images]
        + [{"type": "PRODUCT", "product_id": c} for c in cards]
    }


def _invitation(opts) -> dict:
    name, message = opts.get("invite_name"), opts.get("invite_message")
    contacts = [_contact(c) for c in opts.get("contact") or []]
    missing = [f for f, v in (("--invite-name", name), ("--invite-message", message), ("--contact", contacts)) if not v]
    if missing:
        raise UsageError(
            f"an inline invitation needs {', '.join(missing)}",
            ["--contact is the merchant's real WhatsApp / email / … that creators reply to: ask the user, never invent one"],
        )
    inv: dict = {
        "invite_name": _check_text("--invite-name", name, placeholders=False),
        "invite_message": _check_text("--invite-message", message),
    }
    if opts.get("cooperation"):
        inv["cooperation_type"] = opts["cooperation"]
    if opts.get("no_sample"):
        if opts.get("sample_review"):
            raise UsageError("--sample-review only applies when a sample is offered (drop --no-sample)")
        inv["offer_sample"] = False
    elif opts.get("sample_review"):
        inv["sample_review_type"] = opts["sample_review"]
    inv["contacts"] = contacts
    if opts.get("sync_dm"):
        sync: dict = {"segments": [{"type": "TEXT", "text": _check_text("--sync-dm", opts["sync_dm"])}, {"type": "INVITE_CARD"}]}
        if opts.get("sync_dedup"):
            sync = {"dedup_type": opts["sync_dedup"], **sync}
        inv["sync_dm"] = sync
    elif opts.get("sync_dedup"):
        raise UsageError("--sync-dedup only applies with --sync-dm")
    return inv


def _products(opts, shop: str) -> list[dict]:
    if not opts.get("products"):
        raise UsageError(
            "an inline invitation needs --products",
            [f"Pick selectable=true ids from `boost outreach products --shop {shop} --method TIKTOK_TARGET_COLLABORATION`"],
        )
    out: list[dict] = []
    seen: set = set()
    for item in common.ids([opts["products"]], "product id", PRODUCT_MAX):
        pid, _, rate = item.partition(":")
        pid = pid.strip()
        if pid in seen:
            raise UsageError(f"product {pid} is listed twice in --products")
        seen.add(pid)
        rate = rate.strip() or opts.get("commission")
        if not rate:
            raise UsageError(f"no commission for product {pid}", ["Add --commission 0.15 (15%) for all, or ID:0.15 per product"])
        p = {"product_id": pid, "commission_rate": _ratio(rate, "commission")}
        if opts.get("ads_commission"):
            p["ads_commission_rate"] = _ratio(opts["ads_commission"], "--ads-commission")
        out.append(p)
    return out


def _content_json(opts) -> dict | None:
    raw = opts.get("content")
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        raise UsageError(f"--content is not valid JSON: {e.msg}") from None
    if not isinstance(value, dict):
        raise UsageError("--content must be a JSON object")
    return value


def _inline_content(opts, shop: str, invite: bool) -> dict:
    """`content` of POST /outreach-tasks from --content or the content flags."""
    flags = _given(opts, DM_KEYS + INVITE_KEYS + PRODUCT_KEYS)
    raw = _content_json(opts)
    if raw is not None:
        if flags or opts.get("products"):
            raise UsageError("--content replaces the content flags — pass one or the other", [f"also given: {', '.join(flags or ['--products'])}"])
        return raw
    if invite:
        if _given(opts, DM_KEYS):
            raise UsageError(
                f"{', '.join(_given(opts, DM_KEYS))} build a DM; an invitation uses --invite-name/--invite-message "
                "and --sync-dm for the DM sent with it"
            )
        return {"invitation": _invitation(opts), "products": _products(opts, shop)}
    wrong = _given(opts, INVITE_KEYS + PRODUCT_KEYS) + (["--products"] if opts.get("products") else [])
    if wrong:
        raise UsageError(
            f"{', '.join(wrong)} only apply to --method TIKTOK_TARGET_COLLABORATION",
            ["Product cards in a DM: --card <product_id>"],
        )
    return {"dm": _dm(opts)}


def _start_and_expiry(opts, invite: bool) -> tuple[str | None, str | None]:
    at = common.parse_future(opts.get("at"), "--at")
    if not invite:
        return at, None
    expire = common.parse_future(opts.get("expire"), "--expire")
    if not expire:
        base = (datetime.datetime.fromisoformat(at.replace("Z", "+00:00")) if at
                else datetime.datetime.now(datetime.timezone.utc))
        expire = common.iso(base + DEFAULT_EXPIRE)
    return at, expire


def create(cfg, opts, args):
    shop = common.shop(cfg, opts)
    operator = _operator(opts)
    method = opts.get("method")
    invite = method == "TIKTOK_TARGET_COLLABORATION"
    template = (opts.get("template") or "").strip()
    inline = _given(opts, DM_KEYS + INVITE_KEYS + PRODUCT_KEYS) + (["--content"] if opts.get("content") else [])
    if template and inline:
        raise UsageError(f"--template and inline content ({', '.join(inline)}) are exclusive — pick one")
    if not template and not inline:
        raise UsageError(
            "say what to send: inline content, or --template",
            [
                "DM: --text 'Hi ${handle}! ...' [--image <image_id>] [--card <product_id>] (single quotes keep ${handle} from the shell)",
                "Invitation: --method TIKTOK_TARGET_COLLABORATION --invite-name ... --invite-message ... "
                "--contact WHATSAPP:<number> --products <id> --commission 0.15",
                f"Or an existing template: `boost outreach templates --shop {shop} --method {method}`",
            ],
        )
    creators = common.inputs(args, opts, "creator_oecuid", None)
    if len(creators) > RECIPIENT_MAX:
        raise UsageError(
            f"at most {RECIPIENT_MAX} creators per task, got {len(creators)}",
            [f"Split the list into tasks of up to {RECIPIENT_MAX} — each is its own create with its own --external-id"],
        )
    if any(c.startswith("@") for c in creators):
        raise UsageError(
            "recipients are creator_oecuid values, not handles",
            ["Resolve handles first: `boost creator resolve @handle --region <shop region>`"],
        )
    body: dict = {
        "external_task_id": (opts.get("external_id") or "").strip() or _external_id(),
        "shop_id": shop,
    }
    if operator:
        body["operator_account"] = operator
    body["outreach_method"] = method
    at, expire = _start_and_expiry(opts, invite)
    products = None
    if template:
        if not invite and (opts.get("products") or opts.get("product_template") or opts.get("expire")):
            raise UsageError("--product-template, --expire and --products only apply to --method TIKTOK_TARGET_COLLABORATION")
        body["template_id"] = template
        if invite:
            if not opts.get("product_template"):
                raise UsageError(
                    "a template invitation needs --product-template",
                    [f"Product templates: `boost outreach templates --shop {shop} "
                     "--method TIKTOK_TARGET_COLLABORATION --type INVITE_PRODUCT`"],
                )
            body["invitation"] = {"product_template_id": opts["product_template"].strip(), "expire_at": expire}
        products = common.ids([opts["products"]], "product id", PRODUCT_MAX) if opts.get("products") else None
    else:
        if opts.get("product_template"):
            raise UsageError("--product-template is for template mode; inline invitations list --products with --commission")
        if not invite and opts.get("expire"):
            raise UsageError("--expire only applies to --method TIKTOK_TARGET_COLLABORATION")
        if invite:
            body["invitation"] = {"expire_at": expire}
        body["content"] = _inline_content(opts, shop, invite)
    if at:
        body["schedule"] = {"not_before": at}
    recipients = []
    for c in creators:
        r: dict = {"creator_oecuid": c}
        if products:
            r["channel_product_ids"] = products
        recipients.append(r)
    body["recipients"] = recipients

    ext = body["external_task_id"]
    deadline = time.monotonic() + IN_PROGRESS_DEADLINE
    while True:
        try:
            env = common.send(
                cfg, opts, "POST", "/outreach-tasks", body=body, key=ext, retry_hint=f"--external-id {ext}",
                confirm_flags=f"--external-id {ext} --yes", timeout=CREATE_TIMEOUT,
            )
            break
        except BoostError as e:
            # an earlier attempt (timed out on our side) is still building the task: wait for it
            if "IN_PROGRESS" not in str(e) or time.monotonic() >= deadline:
                raise
            time.sleep(IN_PROGRESS_WAIT)
    if env is None:
        return 0
    data = env.get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("outreach_task", data)
    task = data.get("outreach_task_id")
    as_op = f" --operator {common.shlex.quote(operator)}" if operator else ""
    hints = [
        "Accepted, not sent yet — Kaloboost sends in the background",
        f"Progress: `boost outreach get {task} --shop {shop}`; per creator: `boost outreach recipients {task} --shop {shop}`",
        f"Stop what is not sent yet: `boost outreach cancel {task} --shop {shop}{as_op}`",
    ]
    total = data.get("total_count")
    if invite and isinstance(total, int) and total < len(creators):
        hints.insert(1, f"{len(creators) - total} creator(s) dropped: already invited (duplicate invitations are skipped)")
    render.emit_help(hints)
    return 0


def cancel(cfg, opts, args):
    shop = common.shop(cfg, opts)
    task = args[0]
    env = common.send(
        cfg, opts, "POST", f"/outreach-tasks/{_q(task)}:cancel",
        params={"shop_id": shop, "operator_account": _operator(opts)},
    )
    if env is None:
        return 0
    data = env.get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("outreach_task", data)
    render.emit_help([
        "Only creators not sent yet are stopped — sent messages and invitations can't be recalled",
        "Finished tasks (COMPLETED/PARTIALLY_COMPLETED/FAILED) are returned unchanged",
        f"The status may lag a moment; confirm with `boost outreach get {task} --shop {shop}`",
    ])
    return 0


def templates(cfg, opts, args):
    shop = common.shop(cfg, opts)
    operator = _operator(opts)
    method = opts.get("method")
    ttype = opts.get("type")
    if ttype and method == "TIKTOK_DM":
        raise UsageError("--type only applies to --method TIKTOK_TARGET_COLLABORATION")
    params = {"shop_id": shop, "operator_account": operator, "outreach_method": method, "template_type": ttype}
    rows, cursor, pages = common.fetch_pages(cfg, "/outreach-templates", params, opts)
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": cursor})
        return 0
    who = operator or "your account"
    if not rows:
        render.emit_empty(
            "templates", f"{who}, {method}, shop {shop}",
            ["No template needed: send the content inline (`boost outreach create --help`), "
             "or save one with `boost outreach create-template`"],
        )
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


def products(cfg, opts, args):
    shop = common.shop(cfg, opts)
    method = opts.get("method")
    operator = _operator(opts)
    keyword = (opts.get("keyword") or "").strip() or None
    params = {"shop_id": shop, "outreach_method": method, "operator_account": operator, "keyword": keyword}
    # shares the 1/s outreach_create limit: listing fast can trip a TikTok captcha for the shop
    rows, cursor, pages = common.fetch_pages(cfg, "/outreach-products", params, opts, pace=1.0)
    if opts.get("all"):
        rows = list({r.get("product_id"): r for r in rows}.values())
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": cursor})
        return 0
    if not rows:
        render.emit_empty("products", f"shop {shop}, {method}" + (f", keyword {keyword}" if keyword else ""))
        return 0
    display = []
    for r in rows:
        price = r.get("price") or {}
        lo, hi = price.get("min_format"), price.get("max_format")
        display.append({
            "product_id": r.get("product_id"),
            "title": render.clip(r.get("title"), 50),
            "price": lo if lo == hi or not hi else f"{lo}-{hi}",
            "stock": r.get("stock"),
            "commission_rate": r.get("commission_rate"),
            "selectable": r.get("selectable"),
            "reason": r.get("unselectable_reason"),
        })
    render.emit_table("products", display, ("product_id", "title", "price", "stock", "commission_rate", "selectable", "reason"))
    use = ("in a DM: --card <product_id>" if method == "TIKTOK_DM"
           else "in an invitation: --products <product_id> --commission 0.15")
    hints = [
        f"Only selectable=true products can be sent; use them {use}",
        "Shares the 1 call/s outreach limit with create, upload-image and create-template — call one at a time",
    ]
    base = common.again("outreach products", *common.flag_pairs(shop=shop, method=method, operator=operator, keyword=keyword))
    render.emit_help(common.page_hints(rows, cursor, pages, base, opts, hints))
    return 0


def _image_base64(path: str) -> tuple[str, str]:
    p = Path(path).expanduser()
    try:
        raw = p.read_bytes()
    except OSError as e:
        raise UsageError(f"cannot read {path}: {e.strerror or e}") from None
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        default_name = "image.png"
    elif raw.startswith(b"\xff\xd8\xff"):
        default_name = "image.jpg"
    else:
        raise UsageError(f"{path} is not a JPG or PNG image")
    if len(raw) > IMAGE_MAX_BYTES:
        raise UsageError(f"{path} is {len(raw)} bytes; images are at most 5 MB")
    return base64.b64encode(raw).decode("ascii"), p.name or default_name


def upload_image(cfg, opts, args):
    shop = common.shop(cfg, opts)
    encoded, file_name = _image_base64(args[0])
    body = {"shop_id": shop, "file_base64": encoded, "file_name": (opts.get("name") or file_name)[:128]}
    operator = _operator(opts)
    if operator:
        body["operator_account"] = operator
    # waits in line for the shop's TikTok quota: can take ~75s; a retry only uploads it again
    data = api.request(cfg, "POST", "/outreach-images", body=body, timeout=100.0).get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("image", data)
    render.emit_help([
        f"Use it in a DM to this shop only: `boost outreach create ... --shop {shop} --text ... --image {data.get('image_id')}`",
        "Copy image_id exactly; reuse it for later sends instead of uploading again",
    ])
    return 0


def create_template(cfg, opts, args):
    shop = common.shop(cfg, opts)
    operator = _operator(opts)
    name = (opts.get("name") or "").strip()
    if not name or len(name) > 50:
        raise UsageError("--name is required, 1-50 characters", ["The name the merchant sees in the Kaloboost console"])
    raw = _content_json(opts)
    kinds = {
        "dm": _given(opts, DM_KEYS),
        "invitation": _given(opts, INVITE_KEYS),
        "products": _given(opts, PRODUCT_KEYS) + (["--products"] if opts.get("products") else []),
    }
    picked = [k for k, v in kinds.items() if v]
    if raw is not None:
        if picked:
            raise UsageError("--content replaces the content flags — pass one or the other")
        picked = [k for k in ("dm", "invitation", "products") if k in raw]
        if len(picked) != 1 or len(raw) != 1:
            raise UsageError('--content takes exactly one of {"dm": …}, {"invitation": …}, {"products": […]}')
        content = raw[picked[0]]
    else:
        if len(picked) != 1:
            raise UsageError(
                "a template is exactly one of: a DM (--text/--image/--card), invitation content "
                "(--invite-name/--invite-message/--contact/…), or invitation products (--products/--commission)",
                ["An invitation needs two templates — create the content and the products template separately"]
                + ([f"given: {', '.join(f for k in picked for f in kinds[k])}"] if picked else []),
            )
        content = {"dm": _dm, "invitation": _invitation, "products": lambda o: _products(o, shop)}[picked[0]](opts)
    kind = picked[0]
    body: dict = {"shop_id": shop}
    if operator:
        body["operator_account"] = operator
    body["template_name"] = name
    body[kind] = content
    method = "TIKTOK_DM" if kind == "dm" else "TIKTOK_TARGET_COLLABORATION"
    listing = f"boost outreach templates --shop {shop} --method {method}"
    try:
        env = common.send(cfg, opts, "POST", "/outreach-templates", body=body, idempotent=False)
    except BoostError as e:
        if e.kind == "network":
            e.help_lines.append(
                f"It may have been created anyway — look for '{name}' in `{listing}` before trying again; "
                "a retry can leave a duplicate template (it sends nothing)"
            )
        raise
    if env is None:
        return 0
    data = env.get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("template", data)
    tid = data.get("template_id")
    as_op = f" --operator {common.shlex.quote(operator)}" if operator else ""
    use = {
        "dm": f"`boost outreach create <oecuid...> --shop {shop}{as_op} --template {tid}`",
        "invitation": f"`boost outreach create <oecuid...> --shop {shop}{as_op} --method {method} --template {tid} --product-template <id>`",
        "products": f"`boost outreach create <oecuid...> --shop {shop}{as_op} --method {method} --template <content id> --product-template {tid}`",
    }[kind]
    render.emit_help([
        f"Ready now: {use}",
        "Tasks using it must run as the same member (same --operator, or none for your own account)",
        "It also shows in the Kaloboost console, where the merchant can edit it",
    ])
    return 0


def _operator_flag(what: str) -> Flag:
    return Flag(
        "--operator",
        f"Kaloboost member {what}: login email or '+CC NUMBER' (default: the key's own account)",
        metavar="ACCOUNT",
    )


def _content_flags(*, products: bool) -> list[Flag]:
    flags = [
        Flag("--text", "DM text segment, repeatable; ${handle} = the creator's username (no @; single-quote it in a shell)", kind="multi", default=[], metavar="TEXT"),
        Flag("--image", "DM image segment, repeatable: image_id from `outreach upload-image`", kind="multi", default=[], metavar="IMAGE_ID"),
        Flag("--card", "DM product card, repeatable: selectable product_id from `outreach products`", kind="multi", default=[], metavar="PRODUCT_ID"),
        Flag("--invite-name", "invitation title, 1-26 characters, no placeholder", metavar="TEXT"),
        Flag("--invite-message", "invitation message, 1-500 characters, no emoji; ${handle} allowed", metavar="TEXT"),
        Flag(
            "--contact", "merchant contact TYPE:VALUE[:CC], repeatable, e.g. WHATSAPP:812345678:TH, EMAIL:hi@shop.com — "
            "ask the user, never invent", kind="multi", default=[], metavar="CONTACT",
        ),
        Flag("--cooperation", "what the creator should post", choices=COOPERATION, metavar="|".join(COOPERATION)),
        Flag("--no-sample", "don't offer a free sample", kind="flag", default=False),
        Flag("--sample-review", "sample approval (default MANUAL)", choices=("AUTO", "MANUAL"), metavar="AUTO|MANUAL"),
        Flag("--sync-dm", "also DM the creator this text plus the invite card", metavar="TEXT"),
        Flag("--sync-dedup", "skip the sync DM if one was sent within", choices=DEDUP, metavar="|".join(DEDUP)),
    ]
    if products:
        flags.append(Flag("--products", "invitation products ID[:RATE],... — selectable ids from `outreach products`", metavar="IDS"))
    flags += [
        Flag("--commission", "commission ratio for products without their own: 0.15 = 15%", metavar="RATIO"),
        Flag("--ads-commission", "ads commission ratio for all products (turns ads commission on)", metavar="RATIO"),
        Flag("--content", "the whole content as JSON instead of the flags above (API shape, see the API doc)", metavar="JSON"),
    ]
    return flags


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
            _operator_flag("whose templates"),
            Flag("--method", "channel", default="TIKTOK_DM", choices=METHODS, metavar="|".join(METHODS)),
            Flag(
                "--type", "invitation template type (target invitations only)",
                choices=("INVITE_CONTENT", "INVITE_PRODUCT"), metavar="INVITE_CONTENT|INVITE_PRODUCT",
            ),
            *common.page_flags(default_limit=50),
        ],
        examples=["boost outreach templates --shop <SHOP_ID> --method TIKTOK_DM"],
    ),
    Command(
        path="outreach products",
        summary="Shop products usable in a DM product card or a target invitation (selectable or why not)",
        handler=products,
        flags=[
            common.shop_flag(),
            Flag("--method", "channel the products are for", default="TIKTOK_DM", choices=METHODS, metavar="|".join(METHODS)),
            Flag("--keyword", "search product titles", metavar="TEXT"),
            Flag("--operator", "check this member manages the shop (optional)", metavar="ACCOUNT"),
            *common.page_flags(default_limit=20),
        ],
        examples=[
            "boost outreach products --shop <SHOP_ID> --method TIKTOK_TARGET_COLLABORATION",
            "boost outreach products --shop <SHOP_ID> --keyword bottle",
        ],
    ),
    Command(
        path="outreach upload-image",
        summary="Upload a JPG/PNG (≤5 MB) for DM image segments; returns the shop's image_id (can take ~75s)",
        handler=upload_image,
        flags=[
            common.shop_flag(),
            Flag("--name", "file name shown in Kaloboost (default: the file's name)", metavar="NAME"),
            Flag("--operator", "check this member manages the shop (optional)", metavar="ACCOUNT"),
        ],
        positional="image_path",
        pos_min=1,
        pos_max=1,
        examples=["boost outreach upload-image ./bottle.png --shop <SHOP_ID>"],
    ),
    Command(
        path="outreach create",
        summary="Send a TikTok DM or target invitation to creators, content inline or from a template "
                "(prints the request; --yes sends)",
        handler=create,
        flags=[
            common.shop_flag(),
            _operator_flag("the task runs as"),
            Flag("--method", "channel", default="TIKTOK_DM", choices=METHODS, metavar="|".join(METHODS)),
            *_content_flags(products=False),
            Flag(
                "--products", "inline invitation: ID[:RATE],... with --commission; template mode: a subset of "
                "the product template (default: all)", metavar="IDS",
            ),
            Flag("--template", "template mode: DM template / invitation content template id", metavar="TEMPLATE_ID"),
            Flag("--product-template", "template mode: invitation product template id", metavar="TEMPLATE_ID"),
            Flag("--expire", "invitation expiry: 14d (from now) | yyyy-MM-dd | ISO (default: start + 7d)", metavar="WHEN"),
            Flag("--at", "start later: 2h (from now) | yyyy-MM-dd | ISO, at most 90 days ahead (default: now)", metavar="WHEN"),
            Flag("--external-id", "your id for this task; rerun with the same id to retry safely (default: generated)", metavar="ID"),
            common.file_flag("creator_oecuids"),
            common.yes_flag(),
        ],
        positional="creator_oecuid",
        pos_min=0,
        pos_max=None,
        examples=[
            "boost outreach create <OECUID1> <OECUID2> --shop <SHOP_ID> --text 'Hi ${handle}! Free sample of our bottle?' "
            "--card <PRODUCT_ID>",
            "boost outreach create --file creators.txt --shop <SHOP_ID> --method TIKTOK_TARGET_COLLABORATION "
            "--invite-name 'Zupet water bottle' --invite-message 'Hi ${handle}! Free sample?' "
            "--contact WHATSAPP:<merchant number> --products <PRODUCT_ID> --commission 0.15 "
            "--sync-dm 'Hi ${handle}, just sent you an invite!'",
            "boost outreach create <OECUID> --shop <SHOP_ID> --template <TEMPLATE_ID>",
        ],
    ),
    Command(
        path="outreach create-template",
        summary="Save a DM, invitation-content or invitation-products template in Kaloboost "
                "(prints the request; --yes creates)",
        handler=create_template,
        flags=[
            common.shop_flag(),
            _operator_flag("who owns the template"),
            Flag("--name", "template name, 1-50 characters", metavar="NAME"),
            *_content_flags(products=True),
            common.yes_flag(),
        ],
        examples=[
            "boost outreach create-template --shop <SHOP_ID> --name 'Launch DM' --text 'Hi ${handle}!' --image <IMAGE_ID>",
            "boost outreach create-template --shop <SHOP_ID> --name 'Bottle 15%' --products <ID1>,<ID2>:0.2 --commission 0.15",
        ],
    ),
    Command(
        path="outreach cancel",
        summary="Stop the not-yet-sent part of an outreach task (prints the request; --yes sends)",
        handler=cancel,
        flags=[
            common.shop_flag(),
            _operator_flag("the cancel runs as"),
            common.key_flag(),
            common.yes_flag(),
        ],
        positional="outreach_task_id",
        pos_min=1,
        pos_max=1,
        examples=["boost outreach cancel <TASK_ID> --shop <SHOP_ID> --yes"],
    ),
]
