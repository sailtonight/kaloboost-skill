# kaloboost-skill

Agent skill for [Kaloboost](https://www.kaloboost.com) — read a TikTok Shop seller's creator-outreach data: bound shops, creator lookup, outreach tasks and per-creator results, collaborations, free samples and the content posted for them, affiliate orders, change events.

The skill bundles a zero-dependency CLI (`boost`, Python 3.11+ stdlib only). Installing the skill is all it takes: the agent runs the CLI straight from the skill directory. It is read-only.

## Install

```sh
npx skills add sailtonight/kaloboost-skill               # project-level
npx skills add sailtonight/kaloboost-skill -g            # global
```

## Configure

`boost` uses the **KaloData OpenAPI key** — the same key as the [kalodata skill](https://github.com/sailtonight/kalodata-skill)'s `kalo` CLI, read from the same place. If `kalo` already works on the machine, there is nothing to do.

Otherwise get a key at [open-center/account](https://www.kalodata.com/open-center/account) → *generate key*, then:

```sh
export KALODATA_API_KEY=<token>
# or persist it (shared with kalo): ~/.config/kalodata/config.toml
boost config set --key <token>
```

Data is scoped to the key's company, which needs a Kaloboost account with shops bound in Kaloboost; `boost shops` lists what the key can see.

Optional settings:

| setting | env | `boost config set` |
|---|---|---|
| default shop for `--shop` | `KALOBOOST_SHOP` | `--shop <SHOP_ID>` |
| endpoint (default `https://open.kaloboost.com/openapi/v1`) | `KALOBOOST_BASE_URL` | `--env prod\|test` or `--base-url <URL>` |
| upgrade notice | `KALOBOOST_NO_UPDATE_CHECK=1` | `--update-check off` |

The upgrade notice compares the CLI version with the newest tag on GitHub in a detached background process and prints a one-line hint to stderr at most once an hour.

## Usage

```sh
alias boost="python3 skills/kaloboost/scripts/boost.py"

boost                                         # command map + auth status
boost shops                                   # shop ids for --shop
boost outreach list --shop <SHOP_ID> --since 7d
boost sample list --shop <SHOP_ID> --all --status CONTENT_PENDING
boost creator resolve @demo_creator --region US
boost order list --shop <SHOP_ID> --from 30d --all
```

Output is token-efficient TOON; add `--json` for raw JSON. Lists are cursor-paged: follow the `More:` hint (it repeats the flags the cursor is bound to) or add `--all`.

## Commands

| Command | Description |
|---|---|
| `boost capabilities` | Features open for this key, creator regions, rate limits |
| `boost shops` | Bound shops (ids for `--shop`) and per-shop capabilities |
| `boost creator resolve <@handle\|user_id...>` / `get <creator_oecuid...>` | Match creators, read profile and contact |
| `boost outreach list` / `get <id>` / `recipients <id>` / `templates` | Outreach tasks, progress, per-creator results, templates |
| `boost collab list` / `get <id>` | Collaboration records |
| `boost sample list` / `get <id>` / `contents <id>` | Sample requests, fulfillment, posted videos/lives |
| `boost order list` | Affiliate orders by order time (≤90-day window) |
| `boost event list` | Change events of a shop (kept 30 days) |
| `boost config [set]` | Show or save key, default shop, endpoint |

Exit codes: `0` success, `1` error, `2` usage error.

## Development

```sh
uv run --with pytest pytest -q     # tests run against a local mock server, no credentials needed
```

## License

MIT
