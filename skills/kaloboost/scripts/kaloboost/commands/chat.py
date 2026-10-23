"""`boost chat` — the shop's TikTok Shop chats with creators: read, reply, mark read, star, archive."""

from __future__ import annotations

import json
import urllib.parse
import uuid
from pathlib import Path

from .. import api, render
from ..core import Command, Flag
from ..errors import BoostError, UsageError
from . import common

STATUSES = ("ALL", "UNREAD", "UNREPLIED", "STARRED", "ARCHIVED")
ACTIONS = ("STARRED", "UNSTARRED", "ARCHIVED")
LIST_MAX = 50
MESSAGES_MAX = 20
READ_MAX = 20
TEXT_MAX = 2000
CARD_TEXT_MAX = 500
TITLE_MAX = 50
CARD_PRODUCTS_MAX = 5
IMAGE_MAX_BYTES = 10_000_000
_IMAGE_TYPES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

CONVERSATION_FIELDS = ("conversation_id", "username", "unread_count", "creator_im_id")
MESSAGE_FIELDS = ("created_at", "sender_role", "sender_id", "msg_type", "text", "message_id")

_WRITE_LIMIT_HINT = "Chat writes (open, send, upload-image, read, status) share 1 call/s — run them one at a time"


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _operator(opts) -> str | None:
    """--operator, or None: the server then acts as the key's own account."""
    return (opts.get("operator") or "").strip() or None


def _with_operator(body: dict, opts) -> dict:
    operator = _operator(opts)
    if operator:
        body["operator_account"] = operator
    return body


def _key(opts) -> str:
    return opts.get("idempotency_key") or str(uuid.uuid4())


def _write(cfg, opts, method: str, path: str, body: dict) -> dict:
    """A chat POST that doesn't need --yes (it sends nothing to the creator)."""
    key = _key(opts)
    try:
        return api.request(cfg, method, path, body=body, headers={"Idempotency-Key": key})
    except BoostError as e:
        if e.kind == "network" and e.submission is None:
            e.help_lines.append(f"Rerun the identical command with --idempotency-key {key} so it runs at most once")
        raise


# --- reads -------------------------------------------------------------------

def conversations(cfg, opts, args):
    shop = common.shop(cfg, opts)
    status = opts.get("status") or "ALL"
    params = {"shop_id": shop, "conversation_status": status}
    rows, cursor, pages = common.fetch_pages(cfg, "/chat/conversations", params, opts, max_limit=LIST_MAX)
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": cursor})
        return 0
    if not rows:
        render.emit_empty("conversations", f"shop {shop}, {status}", [
            "Start one with a creator: `boost chat open <creator_oecuid> --shop " + shop + "`",
        ])
        return 0
    render.emit_table("conversations", rows, CONVERSATION_FIELDS)
    hints = [
        f"Read one: `boost chat messages <conversation_id> --shop {shop}`",
        "creator_im_id is TikTok's chat id, not creator_oecuid — don't pass it to creator commands",
        "Listing doesn't mark anything read",
    ]
    # chat cursors are bound to the limit too
    base = common.again("chat list", *common.flag_pairs(shop=shop, status=status, limit=common.limit(opts, LIST_MAX)))
    render.emit_help(common.page_hints(rows, cursor, pages, base, opts, hints))
    return 0


def counts(cfg, opts, args):
    shop = common.shop(cfg, opts)
    data = api.request(cfg, "GET", "/chat/conversations/counts", params={"shop_id": shop}).get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    rows = data.get("group_counts") or []
    render.emit_table("conversation_counts", rows, ("group_type", "count"))
    render.emit_help([f"List a group: `boost chat list --shop {shop} --status UNREAD`"])
    return 0


def _text(m: dict):
    """One readable line per message; the raw content stays in --json."""
    c = m.get("content")
    if not isinstance(c, dict):
        return render.clip(m.get("content_raw"), 200)
    t = m.get("msg_type")
    if t == "TEXT" and isinstance(c.get("content"), str):
        return render.clip(c["content"], 200)
    if t == "IMAGE":
        return f"[image] {c.get('url')}"
    if t == "PRODUCT_CARD":
        return f"[product] {c.get('product_id')}"
    if isinstance(c.get("content"), str):
        title = f"{c['title']}: " if c.get("title") else ""
        return f"[{(t or 'card').lower()}] " + render.clip(title + c["content"], 200)
    return render.clip(json.dumps(c, ensure_ascii=False, separators=(",", ":")), 200)


def messages(cfg, opts, args):
    shop = common.shop(cfg, opts)
    conversation = args[0]
    rows, cursor, pages = common.fetch_pages(
        cfg, f"/chat/conversations/{_q(conversation)}/messages", {"shop_id": shop}, opts, max_limit=MESSAGES_MAX,
    )
    if opts.get("json"):
        common.dump_json({"data": rows, "next_cursor": cursor})
        return 0
    if not rows:
        render.emit_empty("messages", f"conversation {conversation}", [
            f"Send the first one: `boost chat send {conversation} --shop {shop} --text '...'`",
        ])
        return 0
    display = [{**{k: m.get(k) for k in MESSAGE_FIELDS}, "text": _text(m)} for m in rows]
    render.emit_table("messages", display, MESSAGE_FIELDS)
    hints = [
        ("sender_role is often UNKNOWN: a sender_id equal to the conversation's creator_im_id (`boost chat list` / "
         "`chat open`) is the creator, any other is the shop"),
        f"Reply: `boost chat send {conversation} --shop {shop} --text '...'` (dry run first)",
        "Reading doesn't mark the conversation read",
    ]
    base = common.again("chat messages", conversation,
                        *common.flag_pairs(shop=shop, limit=common.limit(opts, MESSAGES_MAX)))
    render.emit_help(common.page_hints(rows, cursor, pages, base, opts, hints))
    return 0


# --- writes ------------------------------------------------------------------

def open_conversation(cfg, opts, args):
    shop = common.shop(cfg, opts)
    body = _with_operator({"shop_id": shop, "creator_oecuid": args[0]}, opts)
    data = _write(cfg, opts, "POST", "/chat/conversations", body).get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("conversation", data)
    cid = data.get("conversation_id")
    render.emit_help([
        f"History: `boost chat messages {cid} --shop {shop}`",
        f"Send: `boost chat send {cid} --shop {shop} --text '...'` (dry run first)",
        "Opening a conversation sends nothing to the creator",
    ])
    return 0


def _content(opts) -> tuple[str, dict]:
    """Pick msg_type from the flags given and build its content object."""
    text = opts.get("text")
    image = (opts.get("image") or "").strip() or None
    products = common.ids(opts["product"], "product id") if opts.get("product") else []
    collab = (opts.get("collab") or "").strip() or None
    sample = (opts.get("sample") or "").strip() or None
    title = opts.get("title")
    if text is not None and not text.strip():
        raise UsageError("--text is empty")

    given = [n for n, v in (("--text", text), ("--image", image), ("--product", products),
                            ("--collab", collab), ("--sample", sample)) if v]
    if not given:
        raise UsageError(
            "nothing to send",
            ["Pass --text, --image (with --width/--height), --product, --collab or --sample (see --help)"],
        )
    for alone in ("--collab", "--sample"):
        if alone in given and len(given) > 1:
            raise UsageError(f"{alone} is a card of its own — send it without other content flags")
    if image and products:
        raise UsageError("a message holds an image or products, not both — send two messages")

    if collab:
        mtype, content = "TARGET_COLLABORATION_CARD", {"target_collaboration_id": collab}
    elif sample:
        mtype, content = "FREE_SAMPLE_CARD", {"apply_id": sample}
    elif text and image:
        mtype, content = "CRM_TEXT_WITH_IMAGE_CARD", {"image_url": image, "content": text}
    elif text and products:
        if len(products) > CARD_PRODUCTS_MAX:
            raise UsageError(f"a text-with-products card takes 1-{CARD_PRODUCTS_MAX} products, got {len(products)}")
        mtype, content = "CRM_TEXT_WITH_PRODUCTS_CARD", {"product_ids": ",".join(products), "content": text}
    elif products:
        if len(products) > 1:
            raise UsageError("a product card is one --product; add --text to send up to 5 in one card")
        mtype, content = "PRODUCT_CARD", {"product_id": products[0]}
    elif image:
        width, height = opts.get("width"), opts.get("height")
        if not width or not height or width < 1 or height < 1:
            raise UsageError("--image needs --width and --height", ["All three come from `boost chat upload-image`"])
        mtype, content = "IMAGE", {"url": image, "width": width, "height": height}
    else:
        mtype, content = "TEXT", {"content": text}

    if mtype == "TEXT" and len(text) > TEXT_MAX:
        raise UsageError(f"--text is {len(text)} characters; a text message holds at most {TEXT_MAX}")
    if mtype.startswith("CRM_"):
        if len(text) > CARD_TEXT_MAX:
            raise UsageError(f"--text is {len(text)} characters; with an image or products at most {CARD_TEXT_MAX}")
        if title is not None:
            if not title.strip() or len(title) > TITLE_MAX:
                raise UsageError(f"--title must be 1-{TITLE_MAX} characters")
            content["title"] = title
    elif title is not None:
        raise UsageError("--title only goes with --text plus --image or --product")
    if mtype != "IMAGE" and (opts.get("width") or opts.get("height")):
        raise UsageError("--width/--height only go with --image alone")
    if products and not all(p.isdigit() and p.strip("0") for p in products):
        raise UsageError("--product ids must be TikTok product ids (digits)",
                         ["List them with `boost outreach products --shop <SHOP_ID>`"])
    return mtype, content


def send(cfg, opts, args):
    shop = common.shop(cfg, opts)
    conversation = args[0]
    mtype, content = _content(opts)
    body = _with_operator({"shop_id": shop, "msg_type": mtype, "content": content}, opts)
    path = f"/chat/conversations/{_q(conversation)}/messages"
    key = _key(opts)
    try:
        env = common.send(cfg, opts, "POST", path, body=body, key=key,
                          confirm_flags=f"--idempotency-key {key} --yes")
    except BoostError as e:
        if e.kind == "network" and e.submission is None:
            e.help_lines.insert(0, f"It may have been sent — check `boost chat messages {conversation} --shop {shop}` "
                                   "before retrying")
        raise
    if env is None:
        return 0
    data = env.get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("sent", data)
    render.emit_help([
        "accepted=true means TikTok took it — not that the creator received or read it",
        "Messages can't be recalled",
        _WRITE_LIMIT_HINT,
    ])
    return 0


def _image(path: str) -> tuple[bytes, str, str]:
    p = Path(path).expanduser()
    try:
        with p.open("rb") as f:
            raw = f.read(IMAGE_MAX_BYTES + 1)  # never load more than the limit
    except OSError as e:
        raise UsageError(f"cannot read {path}: {e.strerror or e}") from None
    if len(raw) > IMAGE_MAX_BYTES:
        raise UsageError(f"{path} is over {IMAGE_MAX_BYTES:,} bytes, the chat image limit")
    ctype = next((t for magic, t in _IMAGE_TYPES if raw.startswith(magic)), None)
    if ctype is None and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        ctype = "image/webp"
    if ctype is None:
        raise UsageError(f"{path} is not a JPG, PNG, GIF or WebP image")
    return raw, p.name or "image", ctype


def upload_image(cfg, opts, args):
    shop = common.shop(cfg, opts)
    raw, name, ctype = _image(args[0])
    payload = api.multipart(_with_operator({"shop_id": shop}, opts), "file", name, raw, ctype)
    key = _key(opts)
    try:
        env = api.request(cfg, "POST", "/chat/images", raw_body=payload, headers={"Idempotency-Key": key}, timeout=100.0)
    except BoostError as e:
        if e.kind == "network" and e.submission is None:
            e.help_lines.append(f"Rerun the identical command with --idempotency-key {key} so it uploads at most once")
        raise
    data = env.get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("chat_image", data)
    url, w, h = data.get("url"), data.get("width"), data.get("height")
    render.emit_help([
        f"Send it: `boost chat send <conversation_id> --shop {shop} --image '{url}' --width {w} --height {h}`",
        f"Or as a card with text: `... --image '{url}' --text '...' [--title '...']`",
        "Uploading sends nothing; this url is for chat only (outreach DMs use `boost outreach upload-image`)",
    ])
    return 0


def mark_read(cfg, opts, args):
    shop = common.shop(cfg, opts)
    ids = common.ids(args, "conversation id", READ_MAX)
    if len(set(ids)) != len(ids):
        raise UsageError("conversation ids repeat — pass each once")
    body = _with_operator({"shop_id": shop, "conversation_ids": ids}, opts)
    data = _write(cfg, opts, "POST", "/chat/conversations:markRead", body).get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    failed = data.get("failed_conversation_ids") or []
    render.out(f"marked_read: {len(ids) - len(failed)} of {len(ids)}")
    if failed:
        render.out(f"failed[{len(failed)}]: {','.join(failed)}")
        render.emit_help(["Retry only the failed ones, without --idempotency-key (a new key: it's a new operation)"])
    return 0


def set_status(cfg, opts, args):
    shop = common.shop(cfg, opts)
    action = opts.get("action")
    if not action:
        raise UsageError("--action is required", [f"one of: {', '.join(ACTIONS)}"])
    body = _with_operator({"shop_id": shop, "action": action}, opts)
    data = _write(cfg, opts, "POST", f"/chat/conversations/{_q(args[0])}/status", body).get("data") or {}
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("conversation_status", data)
    listed = {"STARRED": "STARRED", "ARCHIVED": "ARCHIVED"}.get(action)
    if listed:
        render.emit_help([f"See them: `boost chat list --shop {shop} --status {listed}`"])
    return 0


def _operator_flag() -> Flag:
    return Flag("--operator", "act as this company member (login email or '+CC NUMBER'); default: the key's own account",
                metavar="ACCOUNT")


COMMANDS = [
    Command(
        path="chat list",
        summary="The shop's chat conversations with creators, unread counts; --status filters",
        handler=conversations,
        flags=[
            common.shop_flag(),
            Flag("--status", "which conversations", default="ALL", choices=STATUSES, metavar="|".join(STATUSES)),
            *common.page_flags(default_limit=20, max_limit=LIST_MAX),
        ],
        examples=["boost chat list --shop <SHOP_ID>", "boost chat list --shop <SHOP_ID> --status UNREPLIED --all"],
    ),
    Command(
        path="chat counts",
        summary="How many conversations are unread / unreplied / archived …",
        handler=counts,
        flags=[common.shop_flag()],
        examples=["boost chat counts --shop <SHOP_ID>"],
    ),
    Command(
        path="chat open",
        summary="Get the conversation with a creator, starting one if needed (sends nothing)",
        handler=open_conversation,
        flags=[common.shop_flag(), _operator_flag(), common.key_flag()],
        positional="creator_oecuid", pos_min=1, pos_max=1,
        examples=["boost chat open <CREATOR_OECUID> --shop <SHOP_ID>"],
    ),
    Command(
        path="chat messages",
        summary="Messages of a conversation, with who sent them",
        handler=messages,
        flags=[common.shop_flag(), *common.page_flags(default_limit=20, max_limit=MESSAGES_MAX)],
        positional="conversation_id", pos_min=1, pos_max=1,
        examples=["boost chat messages <CONVERSATION_ID> --shop <SHOP_ID>"],
    ),
    Command(
        path="chat send",
        summary="Send a message to a creator: text, image, product or invitation/sample card (prints the request; --yes sends)",
        handler=send,
        flags=[
            common.shop_flag(),
            Flag("--text", f"message text (≤{TEXT_MAX} chars; ≤{CARD_TEXT_MAX} with --image or --product)", metavar="TEXT"),
            Flag("--image", "image url from `boost chat upload-image`; alone it needs --width/--height", metavar="URL"),
            Flag("--width", "image width from upload-image", kind="int", min=1, metavar="PX"),
            Flag("--height", "image height from upload-image", kind="int", min=1, metavar="PX"),
            Flag("--product", "TikTok product id; alone: one product card; with --text: up to 5, repeat or comma-separate",
                 kind="multi", default=[], metavar="PRODUCT_ID"),
            Flag("--collab", "invitation card: channel_invite_id from `boost collab get` (not invite_id)", metavar="ID"),
            Flag("--sample", "free-sample card: channel_apply_id from `boost sample get` (not sample_request_id)", metavar="ID"),
            Flag("--title", f"card title with --text plus --image/--product (≤{TITLE_MAX} chars)", metavar="TITLE"),
            _operator_flag(),
            common.key_flag(),
            common.yes_flag(),
        ],
        positional="conversation_id", pos_min=1, pos_max=1,
        examples=[
            "boost chat send <CONVERSATION_ID> --shop <SHOP_ID> --text 'Thanks! The sample ships today.'",
            "boost chat send <CONVERSATION_ID> --shop <SHOP_ID> --text 'Our best sellers' --product <ID>,<ID>",
            "boost chat send <CONVERSATION_ID> --shop <SHOP_ID> --image <URL> --width 800 --height 600",
        ],
    ),
    Command(
        path="chat upload-image",
        summary="Upload a JPG/PNG/GIF/WebP (≤10 MB) for chat; returns url, width, height (sends nothing)",
        handler=upload_image,
        flags=[common.shop_flag(), _operator_flag(), common.key_flag()],
        positional="image_path", pos_min=1, pos_max=1,
        examples=["boost chat upload-image ./bottle.png --shop <SHOP_ID>"],
    ),
    Command(
        path="chat read",
        summary=f"Mark conversations read (1-{READ_MAX}); nothing else marks them read",
        handler=mark_read,
        flags=[common.shop_flag(), _operator_flag(), common.key_flag()],
        positional="conversation_id", pos_min=1, pos_max=None,
        examples=["boost chat read <CONVERSATION_ID> --shop <SHOP_ID>"],
    ),
    Command(
        path="chat status",
        summary="Star, unstar or archive a conversation",
        handler=set_status,
        flags=[
            common.shop_flag(),
            Flag("--action", "what to do", choices=ACTIONS, metavar="|".join(ACTIONS)),
            _operator_flag(),
            common.key_flag(),
        ],
        positional="conversation_id", pos_min=1, pos_max=1,
        examples=["boost chat status <CONVERSATION_ID> --shop <SHOP_ID> --action STARRED"],
    ),
]
