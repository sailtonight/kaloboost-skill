---
name: kaloboost
description: >
  Read a TikTok Shop seller's Kaloboost creator-outreach data via the bundled `boost` CLI
  (Python, zero install): bound shops, creator lookup by handle (contact email, followers, GMV
  band), outreach tasks (TikTok DM / target invitations) and per-creator send results,
  collaboration status, free-sample requests and the videos creators posted for them,
  affiliate orders with commission, and change events. Use whenever the user asks about their
  Kaloboost account or TikTok Shop affiliate operations — 达人建联、私信/定向邀约触达、建联任务进度、
  合作状态、寄样/申样、样品履约、达人发布的视频、联盟订单、佣金 — even if they never say "kaloboost".
---

# Kaloboost creator outreach (`boost`)

Kaloboost is the seller-side creator-outreach tool for TikTok Shop. This skill reads the
Kaloboost data of the company that owns the API key: its bound shops, outreach, collaborations,
samples, affiliate orders. It is read-only — it never sends messages or changes anything.

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
| `boost creator resolve <@handle\|user_id...>` | TikTok creator → creator_oecuid; --region |
| `boost creator get <creator_oecuid...>` | profile, contact email/phone, followers, GMV band; --region |
| `boost outreach list` | outreach tasks + send progress; --since |
| `boost outreach get <task_id>` | schedule, invitation products, commission |
| `boost outreach recipients <task_id>` | per-creator send result and failure reason |
| `boost outreach templates` | a member's DM / invitation templates; --operator --method |
| `boost collab list` | collaboration records: cooperate_status, outreach_result; --since |
| `boost collab get <id>` | one collaboration record |
| `boost sample list` | sample requests: status, product, commission, content counts; --since --status |
| `boost sample get <id>` | SKUs, fulfillment, status timeline |
| `boost sample contents <id>` | videos/lives posted for a sample: views, likes, orders |
| `boost order list` | affiliate orders by order time; --from --to (≤90 days) |
| `boost event list` | change events (outreach, collab, sample); --types --since |
| `boost config` | show/set key (shared with kalo), default shop, endpoint |

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
  into one event, so they are not a step-by-step history.
