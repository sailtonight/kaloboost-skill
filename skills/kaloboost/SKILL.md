---
name: kaloboost
description: >
  Use for TikTok Shop creator outreach and affiliate operations, or any question about the
  user's Kaloboost account: DM or invite creators (content, shop products, images inline) and
  cancel outreach, look up creators by handle (email, followers, GMV), save templates, track
  outreach progress and per-creator results, read and reply to creator chats (TikTok Shop
  站内信), collaboration status, free samples, creator videos and metrics, affiliate orders and
  commission, change events and webhooks — 达人建联、发私信/定向邀约、建联进度、取消建联、
  达人聊天/站内信收发、合作状态、寄样/申样、达人视频、联盟订单、佣金归因、事件推送.
  Runs via the bundled `boost` CLI (Python, zero install); use it even if the user never
  says "kaloboost".
---

# Kaloboost creator outreach (`boost`)

Kaloboost is the seller-side creator-outreach tool for TikTok Shop. This skill works on the
Kaloboost data of the company that owns the API key: its bound shops, outreach, collaborations,
chats with creators, samples, content, affiliate orders, events. Most commands read. The `[write]`
commands send messages to real creators or change webhook settings — see "Writes" below before
using them.

## Run

The CLI ships inside this skill (`scripts/boost.py`, Python 3.11+ stdlib only — nothing to install):

```sh
python3 <this-skill-dir>/scripts/boost.py shops
```

All examples below write `boost` as shorthand for `python3 <this-skill-dir>/scripts/boost.py`.

Output is TOON (token-oriented) on stdout; add `--json` to any command for raw JSON.
Errors are structured on stdout with actionable `help:` lines. Exit codes: 0 ok, 1 error, 2 usage.

## Setup — check this before the first query

Every command needs a KaloData OpenAPI key (sent as the `secret-key` header). It is the same key
the `kalo` CLI of the kalodata skill uses, stored in the same place. Before the first query of a
session run `boost config` and look at `api_key`. If it says `missing`, stop — don't guess a key
and don't retry the query. Walk the user through these steps and wait:

1. **Get a key** — sign in at https://www.kalodata.com/open-center/account and click
   *generate key*. No account yet? Register at https://www.kalodata.com/open-center/home first.
2. **Save it** — `boost config set --key <API_KEY>` (stored in `~/.config/kalodata/config.toml`,
   mode 0600, shared with `kalo`), or set `KALODATA_API_KEY` in the environment.
3. **Access** — data is scoped to the key's company, which needs a Kaloboost account with shops
   bound in Kaloboost. `boost shops` lists what the key can see; an empty list or a
   `COMPANY_NOT_BOUND` error means this company has no Kaloboost data.

**The API key is the only credential.** Never ask the user for a browser login, password,
cookie, `localStorage` / `ssoAccessToken` or any other token, and don't try to sign in to the
Kaloboost website or call its internal APIs: those credentials don't work with this API, and
going around it is not allowed. On `401` / `403` follow the `help:` lines (`ACCOUNT_NOT_ELIGIBLE`
names what the account still needs) — another credential won't fix them.

## First steps in a session

1. `boost shops` — shop ids for `--shop`, and per-shop capabilities. If the user has one shop, or
   names one, save it: `boost config set --shop <SHOP_ID>` so later commands can omit `--shop`.
2. `boost capabilities` if a command answers `CAPABILITY_UNAVAILABLE` — features marked
   `PLANNED`/`UNAVAILABLE` are not open for this key; tell the user instead of retrying.

## Commands

| command | what |
|---|---|
| `boost capabilities` | which features are open for this key; creator regions; rate limits |
| `boost shops` | bound shops → shop_id for --shop; per-shop capabilities |
| `boost creator resolve <@handle\|user_id...>` | TikTok creator → creator_oecuid (≤100); --region |
| `boost creator get <creator_oecuid...>` | profile, contact email/phone, followers, GMV band; --region |
| `boost creator changes` | creators of a region whose profile or metrics changed; --since |
| `boost resolve-job create\|get\|results` | async resolve of up to 10,000 handles / user ids |
| `boost outreach list` | outreach tasks + send progress; --since |
| `boost outreach get <task_id>` | schedule, invitation products, commission |
| `boost outreach recipients <task_id>` | per-creator send result and failure reason |
| `boost outreach templates` | DM / invitation templates; --method |
| `boost outreach products` | shop products usable in a DM card / invitation, selectable or why not; --method |
| `boost outreach upload-image <path>` | JPG/PNG (≤5 MB) → `image_id` for DM image segments (can take ~75s) |
| `boost outreach create <creator_oecuid...>` | `[write]` send a DM / target invitation, content inline or from a template |
| `boost outreach create-template` | `[write]` save a DM / invitation template in Kaloboost for reuse |
| `boost outreach cancel <task_id>` | `[write]` stop what is not sent yet |
| `boost chat list` | chat conversations with creators, unread counts; --status UNREAD\|UNREPLIED\|STARRED\|ARCHIVED |
| `boost chat counts` | how many conversations are unread / unreplied / archived |
| `boost chat open <creator_oecuid>` | get or start the conversation with a creator → `conversation_id` (sends nothing) |
| `boost chat messages <conversation_id>` | a conversation's messages, sender role (CREATOR / MERCHANT / UNKNOWN) |
| `boost chat upload-image <path>` | JPG/PNG/GIF/WebP (≤10 MB) → url, width, height for chat images |
| `boost chat send <conversation_id>` | `[write]` reply: text, image, product card, text + image/products card, invitation or sample card |
| `boost chat read <conversation_id...>` | mark conversations read (only when the user asks) |
| `boost chat status <conversation_id>` | star / unstar / archive a conversation (only when the user asks) |
| `boost collab list` | collaboration records: cooperate_status, outreach_result; --since |
| `boost collab get <id>` | one collaboration record |
| `boost sample list` | sample requests: status, product, commission, content counts; --since --status |
| `boost sample get <id>` | SKUs, fulfillment, status timeline |
| `boost sample contents <id>` | videos/lives posted for a sample: views, likes, orders |
| `boost content list` / `get <id>` | creator videos/lives of a shop with metrics; --creator --published-from |
| `boost order list` | affiliate orders by order time; --from --to (≤90 days) |
| `boost attribution list` / `get <id>` | affiliate attribution per order line; --creator --order --since |
| `boost event list` | change events (outreach, collab, sample, new chat message); --types --since |
| `boost webhook list` | push endpoints for change events |
| `boost webhook create\|update\|rotate-secret\|test\|replay` | `[write]` manage push endpoints |
| `boost config` | show/set key (shared with kalo), default shop, endpoint |

`content`, `attribution` and `creator changes` follow the published API but may still answer
`CAPABILITY_UNAVAILABLE` (`PLANNED` / `NOT_IMPLEMENTED`) — tell the user the feature isn't live yet.

## Writes

`[write]` commands never act on the first run: without `--yes` they print the exact request
(`dry_run:`) and send nothing. Show it to the user, get an explicit yes, then rerun with the flags
the hint gives (`--yes`, plus `--external-id` for `outreach create`). Never add `--yes` on your own.

- **Send outreach** — write the content inline; no template or Kaloboost console needed:
  1. `boost creator resolve @handle --region <shop region>` → `creator_oecuid` (only `MATCHED`;
     tell the user about `NOT_FOUND` / `AMBIGUOUS`, don't guess). This API can't search creators
     by category / followers / region — the user supplies the handles.
  2. Products (invitations need them; DMs only for a product card):
     `boost outreach products --shop S --method <METHOD>` → use only `selectable=true` ids.
  3. Optional DM image: `boost outreach upload-image ./pic.png --shop S` → `image_id`.
  4. Dry run, then the user confirms, then the same command + `--external-id <id from the hint> --yes`:
     - DM: `boost outreach create <oecuid...> --shop S --text 'Hi ${handle}! ...' [--image <image_id>] [--card <product_id>]`
     - Target invitation: `boost outreach create <oecuid...> --shop S --method TIKTOK_TARGET_COLLABORATION
       --invite-name '<≤26 chars>' --invite-message 'Hi ${handle}! ...' --contact WHATSAPP:<number>
       --products <id>[,<id>:0.2] --commission 0.15 [--sync-dm 'Hi ${handle}, just sent you an invite!']`
  5. `boost outreach recipients <task_id> --shop S` for per-creator results (`Accepted` ≠ sent).
     Failures such as `TARGET_INVITATION_UNAVAILABLE_CREATOR` are about the creator, not the
     request: report them and ask the user for other creators instead of resending.
- **Content rules** (checked before sending):
  - The creator placeholder is `${handle}` — it becomes the creator's TikTok username, without
    `@`; don't put `@` in front. Any other form (`{creator}`, `{{name}}`, `$name`) is rejected.
    **Single-quote** text with `${handle}` in a shell, or the shell replaces it with nothing.
  - `--contact` is the merchant's real WhatsApp / email / LINE / … that creators reply to. Ask the
    user for it; never invent one, reuse an example, or take a member's login phone / email for it. Numbers without country prefix or `+`
    (`WHATSAPP:812345678:TH`; the country code defaults to the shop's market).
  - Commission is a ratio 0.01–0.80: 15% is `0.15`. Invite name ≤26 characters, no placeholder;
    invite message ≤500 characters, no emoji. DMs: ≤5 segments, ≤3 images, ≤1950 chars per text.
  - Inline content is all-or-nothing: an unavailable product or bad contact rejects the request
    (nothing is created) — fix what the error names and send again.
- **Templates** are only for content the merchant wants to reuse. `boost outreach templates` lists
  them; `boost outreach create-template --name ... <same content flags>` saves one (an invitation
  needs two: content, and products). Send with `--template <id>` (invitations add
  `--product-template <id>`); template content can't be overridden per request.
- `--operator` is optional: without it everything runs as the key's own Kaloboost account, which
  is what the user normally wants. Only pass a member (login email or `'+86 13800000000'`) when
  the user asks to act as that member or `SHOP_NOT_AUTHORIZED [operator_account/...]` says the own
  account can't manage the shop — then ask the user which member to use; never pick one yourself.
- Up to 10,000 creators per task — no need to split (`--file` for long lists). Big tasks take 1–3
  minutes to create; the CLI waits for them, so let it run. Invitations expire 7 days after the
  start by default (`--expire`); `--at` schedules up to 90 days ahead.
- Outreach calls (create, create-template, upload-image, products) share a limit of 1 call per
  second: run them one at a time. A `503` asking to wait minutes (TikTok verification for the
  shop) means stop and tell the user — don't retry right away.
- **Retrying**: if a write ends with "outcome is unknown" (timeout / 503), rerun the identical
  command with the `--external-id` / `--idempotency-key` the hint shows — it then runs at most
  once. Never retry an outreach with a new external id: that sends a second task.
  `create-template` has no such key: check `boost outreach templates` for it before retrying.
- `CAPABILITY_UNAVAILABLE ... NOT_IMPLEMENTED` on inline content, products, images or template
  creation means this environment (the test env) doesn't have them yet: tell the user; don't
  work around it.
- Sent messages and invitations can't be recalled; `outreach cancel` only stops unsent ones.

## Chat with creators

One-to-one TikTok Shop chat between the shop and a creator — replying to what a creator wrote,
following up after an invitation or sample. (Bulk first contact is `outreach create`.)

1. Find the conversation: `boost chat list --shop S --status UNREPLIED` (or `UNREAD`), or for a
   given creator `boost chat open <creator_oecuid> --shop S` (resolve `@handle` first; opening
   sends nothing). `creator_im_id` in the output is TikTok's chat id, not a `creator_oecuid`.
2. Read before replying: `boost chat messages <conversation_id> --shop S`. `sender_role` is often
   `UNKNOWN`; then a `sender_id` equal to the conversation's `creator_im_id` is the creator, any
   other sender is the shop. Old messages don't have the same shape as what you send — build a
   reply from the send flags, don't copy their content.
3. Draft the reply, dry-run `boost chat send <conversation_id> --shop S ...`, show it, and only after
   the user confirms rerun it with `--idempotency-key <key from the dry run> --yes`. The flags pick
   the message type:
   - `--text '...'` (≤2000 chars) — plain text
   - `--image <url> --width W --height H` — url and size from `boost chat upload-image ./pic.png --shop S`
   - `--product <id>` — one product card; `--text '...' --product <id>,<id>` — text with 1–5 products
   - `--text '...' --image <url> [--title '...']` — text-with-image card (text ≤500, title ≤50)
   - `--collab <channel_invite_id>` (from `boost collab get`) — the invitation card;
     `--sample <channel_apply_id>` (from `boost sample get`) — the free-sample card. Not the local
     `invite_id` / `sample_request_id`.
4. `accepted=true` only means TikTok took it, not delivered or read.

- New messages: `boost event list --shop S --types chat.message.created --since 1h` (or a webhook
  with that type). Events hold no text — read it with `chat messages`. Events can be late or
  missing: poll `chat list --status UNREAD` too.
- Nothing marks a conversation read except `boost chat read`; reading or listing doesn't. Leave
  conversations unread, and don't star / archive, unless the user asks — the merchant's team uses
  those states in the Kaloboost inbox.
- **Retrying a send**: if it fails with "may already have been sent" (`OUTCOME_UNKNOWN`) or a
  network error, run `chat messages` first; if the message isn't there, rerun the identical command
  with the same `--idempotency-key`. Only `NOT_SUBMITTED` is safe to rerun straight away. Never
  resend with a new key — the creator would get it twice. Keys are kept 24h.
- Chat writes (open, send, upload-image, read, status) share 1 call per second: one at a time.
  `PLATFORM_REJECTED` is TikTok refusing (quota, risk control, content) — tell the user, don't resend.
- `--operator` works as for outreach: leave it out unless the user asks to act as another member.

## Conventions

- Shop-level commands need `--shop <shop_id>` from `boost shops` (or a saved default)
- Lists take `--limit` (1-100) `--cursor` `--all`. To page, run the exact command in the `More:`
  hint — a cursor only works with the same `--shop`/`--since`/`--from`/`--to` it was issued with,
  and expires after 24h. `--all` follows cursors for up to 20 pages
- `--since` / `--from` / `--to` take `30m`, `24h`, `7d`, `yyyy-MM-dd` or ISO 8601 UTC
- Creator commands are per market: `--region US` (default), GB ID TH VN PH MY SG JP MX BR DE ES FR IT NL IE PL
- Run `boost <command> --help` for per-command flags and examples

## Typical flows

- Outreach progress: `boost outreach list --shop S --since 7d` → `boost outreach recipients <task_id> --shop S`
- Who agreed to work with us: `boost collab list --shop S --since 30d --all` → filter `cooperate_status`
- Sample follow-up: `boost sample list --shop S --all --status CONTENT_PENDING` (shipped, no post yet)
  → `boost creator get <creator_oecuid> --region <shop region>` for the contact email
- Did the samples pay off: `boost sample contents <id> --shop S` (views, orders per video) and
  `boost order list --shop S --from 30d --all` (affiliate GMV and commission by creator)
- Look up a creator: `boost creator resolve @handle --region US` → `boost creator get <creator_oecuid>`
- Many creators (>100): `boost resolve-job create --file handles.txt --region US` → `boost resolve-job get <job_id>`
  until it finishes → `boost resolve-job results <job_id> --all`
- Reply to creators: `boost chat list --shop S --status UNREPLIED` → `boost chat messages <id> --shop S`
  → `boost chat send <id> --shop S --text '...'` (dry run → user confirms → `--idempotency-key <key> --yes`)
- Get pushed instead of polling: `boost webhook create --url https://... --shop S` (dry run → `--yes`);
  store the one-time `secret`. Missed events: `boost webhook replay <endpoint_id> --from 24h`

## Reading the data right

- **Creator GMV**: `gmv` is exact for only ~2–5% of creators; `"0"` or null means *unknown*, not
  zero. Quote `gmv_range` to the user, and never rank or drop creators by `gmv`.
- **Outreach counts**: `total − sent_ok − sent_fail` is not-yet-sent or canceled, not failed.
  `AUTOMATION` tasks may never finish; their counts keep growing.
- **Collaboration**: `cooperate_status` is the shop↔creator relationship (COOPERATED >
  SAMPLE_COOPERATED > NOT_COOPERATED); `outreach_result` is this one invitation (null for DMs).
  Times before 2026-09-11 can be ~8h late.
- **Samples**: no status is final (COMPLETED/CANCELED/EXPIRED can still change) — `curr_status`
  is the truth. `delivered_time` is always null today. `--since` can miss some changes; for a
  complete picture list without `--since`. `sample get` on an old id may return a new merged id.
- **Sample content metrics** are snapshots, often stale for older posts; don't sum across calls.
- **Affiliate orders** are read live from TikTok (only US/ID/TH/MY/VN/PH/SG shops that authorized
  TikTok Shop Open API in Kaloboost; others answer `CHANNEL_NOT_AVAILABLE`). Settlement and
  refunds change after the fact — re-pull the window rather than adding up earlier runs. Use
  `--all` for complete orders: one order can span two pages.
- **Events** reflect the object at detection time and are kept 30 days; several changes can merge
  into one event, so they are not a step-by-step history. Webhooks push the same events.
- **Outreach create** answers `Accepted` before anything is sent; target invitations skip creators
  already invited, so `total_count` can be below the number you sent.
- **Stay inside this CLI.** For Kaloboost questions answer from what `boost` returns, scoped to the
  key's own company. Don't go looking for Kaloboost databases, tables or web-console APIs, and
  don't mix in data from other tools unless the user asks for it.
