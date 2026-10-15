# kaloboost-skill

Agent skill for [Kaloboost](https://www.kaloboost.com) — a TikTok Shop seller's creator outreach: bound shops, creator lookup, sending and canceling TikTok DMs / target invitations, per-creator results, collaborations, free samples and the content posted for them, affiliate orders and attribution, change events and webhooks.

The skill bundles a zero-dependency CLI (`boost`, Python 3.11+ stdlib only). Installing the skill is all it takes: the agent runs the CLI straight from the skill directory. It covers every endpoint of the Kaloboost OpenAPI v1.

Write commands (`outreach create/cancel`, `webhook create/update/rotate-secret/test/replay`) only print the request until you add `--yes`.

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
boost outreach create <CREATOR_OECUID> --shop <SHOP_ID> --operator member@example.com --template <TEMPLATE_ID>   # dry run; add --yes to send
```

Output is token-efficient TOON; add `--json` for raw JSON. Lists are cursor-paged: follow the `More:` hint (it repeats the flags the cursor is bound to) or add `--all`.

## Commands

| Command | Description |
|---|---|
| `boost capabilities` | Features open for this key, creator regions, rate limits |
| `boost shops` | Bound shops (ids for `--shop`) and per-shop capabilities |
| `boost creator resolve` / `get` / `changes` | Match creators, read profile and contact, region change feed |
| `boost resolve-job create` / `get` / `results` | Async resolve of up to 10,000 creators |
| `boost outreach list` / `get` / `recipients` / `templates` | Outreach tasks, progress, per-creator results, templates |
| `boost outreach create` / `cancel` | Send a DM / target invitation, stop unsent parts (`--yes`) |
| `boost collab list` / `get` | Collaboration records |
| `boost sample list` / `get` / `contents` | Sample requests, fulfillment, posted videos/lives |
| `boost content list` / `get` | Creator videos/lives of a shop with metrics |
| `boost order list` | Affiliate orders by order time (≤90-day window) |
| `boost attribution list` / `get` | Affiliate attribution per order line |
| `boost event list` | Change events of a shop (kept 30 days) |
| `boost webhook list` / `create` / `update` / `rotate-secret` / `test` / `replay` | Event push endpoints (`--yes` for changes) |
| `boost config [set]` | Show or save key, default shop, endpoint |

Exit codes: `0` success, `1` error, `2` usage error.

## Local MCP server

The repository also includes a stdio MCP server exposing every command except `config`
as a tool, e.g. `shops`, `creator_resolve`, `outreach_list`, `sample_list`,
`outreach_create` and `webhook_rotate_secret`. It shares the CLI's API client,
configuration and validation. The CLI remains usable with Python's standard library only;
MCP dependencies are installed separately through the `mcp` extra.

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then add this
configuration to your MCP client. This installs directly from GitHub; no PyPI release or
manual clone is required:

```json
{
  "mcpServers": {
    "kaloboost": {
      "command": "uvx",
      "args": [
        "--python", ">=3.11",
        "--from",
        "kaloboost-mcp[mcp] @ git+https://github.com/sailtonight/kaloboost-skill",
        "kaloboost-mcp"
      ],
      "env": {
        "KALODATA_API_KEY": "YOUR_API_KEY",
        "KALOBOOST_SHOP": "OPTIONAL_DEFAULT_SHOP_ID"
      }
    }
  }
}
```

For a local checkout, use this configuration (replace the absolute path):

```json
{
  "mcpServers": {
    "kaloboost": {
      "command": "uv",
      "args": [
        "run", "--directory", "/absolute/path/to/kaloboost-skill",
        "--extra", "mcp", "kaloboost-mcp"
      ],
      "env": {
        "KALODATA_API_KEY": "YOUR_API_KEY"
      }
    }
  }
}
```

The client launches and manages the server process. `--python ">=3.11"` lets uv fetch a
suitable Python when the system one is older. If your desktop client cannot find
`uv`/`uvx`, use the executable's absolute path. Existing `boost config set ...` / `kalo`
configuration also works; environment variables take precedence.

Tool names are the command path with `_`, e.g. `resolve-job create` → `resolve_job_create`.
Arguments use flag names without `--` and with `_` for `-`, e.g.
`outreach_list({"shop":"<SHOP_ID>","since":"7d","limit":50})`. Commands that take several
ids use a string array, e.g. `creator_get({"ids":["<CREATOR_OECUID>"]})`; single-id
commands take a named argument, e.g. `outreach_get({"outreach_task_id":"<ID>"})`.
Tools return raw JSON under `data`, matching the CLI's `--json` mode; `json` and `file`
(local file input) are not exposed. Lists return `next_cursor`; pass it back as `cursor`,
or set `all: true`.

Write tools (`outreach_create`, `outreach_cancel`, `webhook_create/update/rotate_secret/test/replay`)
send nothing without `yes: true`: they return a `dry_run` preview plus a `next` hint naming
the `idempotency_key` (or `external_id` for `outreach_create`) to pass along when the user
confirms, so a retried call runs at most once.

To run the server manually from a checkout:

```sh
uv run --extra mcp kaloboost-mcp
```

This starts the protocol on stdin/stdout and waits for a client. It does not start an
HTTP server.

## Development

```sh
uv run --with pytest pytest -q     # tests run against a local mock server, no credentials needed
uv run --extra mcp --with pytest pytest -q  # includes MCP protocol and subprocess tests
uv build                          # build an installable wheel and source archive
```

## License

MIT
