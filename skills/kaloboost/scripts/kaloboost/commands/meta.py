"""`boost config` — show/save credentials and defaults."""

from __future__ import annotations

from .. import config as config_mod
from .. import onboarding, render
from ..core import Command, Flag
from ..errors import UsageError
from . import common


def config_show(cfg, opts, args):
    path = config_mod.config_path()
    masked = "missing"
    if cfg.api_key:
        masked = f"set (…{cfg.api_key[-4:]})" if len(cfg.api_key) > 4 else "set"
    data = {
        "file": str(path) + ("" if path.exists() else " (missing)"),
        "api_key": masked + " (shared with kalo)",
        "base_url": cfg.base_url,
        "default_shop": cfg.shop,
        "update_check": "on" if cfg.update_check else "off",
    }
    if opts.get("json"):
        common.dump_json(data)
        return 0
    render.emit_detail("config", data)
    if not cfg.authed:
        render.emit_help(onboarding.SETUP_LINES)
    return 0


def config_set(cfg, opts, args):
    base_url = opts.get("base_url")
    if opts.get("env"):
        if base_url:
            raise UsageError("pass either --env or --base-url, not both")
        base_url = config_mod.TEST_BASE_URL if opts["env"] == "test" else config_mod.DEFAULT_BASE_URL
    updates = {
        "api_key": opts.get("key"),
        "boost_base_url": base_url,
        "boost_shop": opts.get("shop"),
        "boost_update_check": opts.get("update_check"),
    }
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        raise UsageError(
            "nothing to set",
            ["usage: boost config set --key <API_KEY> [--shop <SHOP_ID>] [--env prod|test]"],
        )
    if "boost_update_check" in updates:
        updates["boost_update_check"] = "true" if updates["boost_update_check"] == "on" else "false"
    path = config_mod.save(updates)
    render.out(f"config: saved {', '.join(sorted(updates))} to {path}")
    if "api_key" in updates:
        render.emit_help(["The key is shared with `kalo` (the kalodata skill) — it now uses this key too"])
    return 0


COMMANDS = [
    Command(
        path="config show",
        summary="Show current credentials (masked) and defaults",
        handler=config_show,
        examples=["boost config"],
    ),
    Command(
        path="config set",
        summary="Save credentials/defaults to ~/.config/kalodata/config.toml",
        handler=config_set,
        flags=[
            Flag("--key", "KaloData OpenAPI key (secret-key header; shared with kalo)", metavar="KEY"),
            Flag("--shop", "default shop_id for --shop", metavar="SHOP_ID"),
            Flag("--env", "prod or test Kaloboost endpoint", choices=("prod", "test"), metavar="prod|test"),
            Flag("--base-url", "explicit API base URL", metavar="URL"),
            Flag(
                "--update-check",
                "upgrade notice from GitHub tags (default on)",
                choices=("on", "off"),
                metavar="on|off",
            ),
        ],
        examples=["boost config set --key <token>", "boost config set --shop <SHOP_ID>"],
    ),
]
