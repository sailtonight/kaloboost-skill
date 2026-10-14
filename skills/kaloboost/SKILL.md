---
name: kaloboost
description: >
  Work with a TikTok Shop seller's Kaloboost creator outreach via the bundled `boost` CLI
  (Python, zero install): bound shops, creator lookup by handle (contact email, followers, GMV
  band), sending TikTok DMs / target invitations to creators and canceling them, outreach
  progress and per-creator send results, collaboration status, free-sample requests and the
  videos creators posted, creator content metrics, affiliate orders and attribution with
  commission, change events and webhook endpoints. Use whenever the user asks about their
  Kaloboost account or TikTok Shop affiliate operations — 达人建联、发私信/定向邀约、建联任务进度、
  取消建联、合作状态、寄样/申样、样品履约、达人发布的视频、联盟订单、佣金归因、事件推送 — even if
  they never say "kaloboost".
---

# Kaloboost creator outreach (`boost`)

Kaloboost is the seller-side creator-outreach tool for TikTok Shop. This skill works on the
Kaloboost data of the company that owns the API key: its bound shops, outreach, collaborations,
samples, content, affiliate orders, events. Most commands read. The `[write]` commands send
messages to real creators or change webhook settings — see "Writes" below before using them.

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
| `boost outreach templates` | a member's DM / invitation templates; --operator --method |
| `boost outreach create <creator_oecuid...>` | `[write]` send a DM / target invitation to creators |
| `boost outreach cancel <task_id>` | `[write]` stop what is not sent yet |
| `boost collab list` | collaboration records: cooperate_status, outreach_result; --since |
| `boost collab get <id>` | one collaboration record |
| `boost sample list` | sample requests: status, product, commission, content counts; --since --status |
| `boost sample get <id>` | SKUs, fulfillment, status timeline |
| `boost sample contents <id>` | videos/lives posted for a sample: views, likes, orders |
| `boost content list` / `get <id>` | creator videos/lives of a shop with metrics; --creator --published-from |
| `boost order list` | affiliate orders by order time; --from --to (≤90 days) |
| `boost attribution list` / `get <id>` | affiliate attribution per order line; --creator --order --since |
| `boost event list` | change events (outreach, collab, sample); --types --since |
| `boost webhook list` | push endpoints for change events |
| `boost webhook create\|update\|rotate-secret\|test\|replay` | `[write]` manage push endpoints |
| `boost config` | show/set key (shared with kalo), default shop, endpoint |

`content`, `attribution` and `creator changes` follow the published API but may still answer
`CAPABILITY_UNAVAILABLE` (`PLANNED` / `NOT_IMPLEMENTED`) — tell the user the feature isn't live yet.

## Writes

`[write]` commands never act on the first run: without `--yes` they print the exact request
(`dry_run:`) and send nothing. Show it to the user, get an explicit yes, then rerun with the flags
the hint gives (`--yes`, plus `--external-id` for `outreach create`). Never add `--yes` on your own.

- **Send outreach**: the message text, products and commission come from a template the member
  made in the Kaloboost console — the API can't take free text. Flow:
  1. `boost creator resolve @handle --region <shop region>` → creator_oecuid
  2. `boost outreach templates --shop S --operator <member> --method TIKTOK_DM` → template_id
     (target invitations: `--method TIKTOK_TARGET_COLLABORATION`, a content template plus an
     `--type INVITE_PRODUCT` template)
  3. `boost outreach create <oecuid...> --shop S --operator <member> --template <id>` → dry run
     (invitations add `--method TIKTOK_TARGET_COLLABORATION --product-template <id> --expire 14d`)
  4. user confirms → same command + `--external-id <id from the hint> --yes`
  5. `boost outreach recipients <task_id> --shop S` for per-creator results
- `--operator` is the Kaloboost member the task runs as (login email or `'+86 13800000000'`); the
  member must manage the shop. Up to 500 creators per task (`--file` for long lists); `--at`
  schedules up to 90 days ahead.
- **Retrying**: if a write ends with "outcome is unknown" (timeout / 503), rerun the identical
  command with the `--external-id` / `--idempotency-key` the hint shows — it then runs at most
  once. Never retry an outreach with a new external id: that sends a second task.
- Sent messages and invitations can't be recalled; `outreach cancel` only stops unsent ones.

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
