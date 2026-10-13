"""First-run guide, shown wherever the API key turns out to be missing.

The Setup section of the SKILL.md next to this package mirrors it — keep both
in sync.
"""

from __future__ import annotations

KEY_URL = "https://www.kalodata.com/open-center/account"
SIGNUP_URL = "https://www.kalodata.com/open-center/home"

SETUP_LINES = [
    f'1. Get a key: sign in at {KEY_URL} and click "generate key" '
    f"(no account yet? register at {SIGNUP_URL}). It is the KaloData OpenAPI key — "
    "if `kalo` (the kalodata skill) already works on this machine, the key is already set.",
    "2. Save it: `boost config set --key <API_KEY>`, or set KALODATA_API_KEY in the environment "
    "(shared with `kalo`, stored in ~/.config/kalodata/config.toml).",
    "3. Access: Kaloboost data is scoped to the company the key belongs to — it needs a Kaloboost "
    "account with shops bound in Kaloboost. `boost shops` lists what the key can see.",
]

NO_KEY_MESSAGE = "no KaloData API key configured yet"
