"""HTTP client for the Kaloboost OpenAPI: retries, envelope handling, error translation.

Success bodies are `{"data": ..., "page": {...}, "request_id": ...}`; failures are
`{"error": {"code", "message", "details": [{"field", "reason"}]}, "request_id"}`.
Requests go through KaloData's gateway (data-service), which rejects a bad key
itself with a flat `{"code", "message", "request_id"}` body, and may answer in
the KaloData `{"success", "code", "message", "data"}` envelope — all are
accepted. Never leaks raw upstream errors to stdout — everything becomes a
BoostError with an actionable suggestion.
"""

from __future__ import annotations

import json
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__
from .config import Config
from .errors import BoostError
from .onboarding import NO_KEY_MESSAGE, SETUP_LINES

_RETRIES = 3
_MAX_RETRY_AFTER = 10.0  # seconds; longer waits are surfaced instead of slept through

AUTH_HELP = SETUP_LINES


class _Retryable(Exception):
    def __init__(self, message: str, wait: float | None = None):
        super().__init__(message)
        self.wait = wait


def _require_auth(cfg: Config) -> None:
    if not cfg.api_key:
        raise BoostError(NO_KEY_MESSAGE, kind="auth", help_lines=AUTH_HELP)


def _headers(cfg: Config, has_body: bool) -> dict:
    h = {
        # kaloboost.com's Cloudflare answers 403 / error 1010 to urllib's default UA
        "User-Agent": f"boost/{__version__}",
        "Accept": "application/json",
        "secret-key": cfg.api_key,
        "source-type": "SKILL",
        "skill-version": __version__,
    }
    if has_body:
        h["Content-Type"] = "application/json;charset=UTF-8"
    return h


def _do_request(url: str, data: bytes | None, headers: dict, timeout: float, method: str):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
        raise _Retryable(str(e)) from e


def _parse(raw: bytes):
    try:
        body = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None
    return body if isinstance(body, dict) else None


def _retry_after(headers) -> float:
    try:
        return max(1.0, float(headers.get("Retry-After") or 1))
    except (TypeError, ValueError):
        return 1.0


def _gateway_error(body: dict) -> dict:
    """KaloData-envelope failure -> Boost error shape."""
    return {"code": str(body.get("code") or "GATEWAY_ERROR"), "message": body.get("message"), "details": []}


def _unwrap(body: dict) -> dict:
    """Normalize a success body to the Boost envelope {data, page, request_id}."""
    if "success" in body and "error" not in body:
        inner = body.get("data")
        if isinstance(inner, dict) and "data" in inner and ("page" in inner or "request_id" in inner):
            return inner
        return {"data": inner}
    return body


def _reason(err: dict) -> tuple[str | None, str | None]:
    details = err.get("details") or []
    first = details[0] if details and isinstance(details[0], dict) else {}
    return first.get("field"), first.get("reason")


_CURSOR_HELP = (
    "Drop --cursor and start again from the first page. A cursor only works with the exact "
    "--shop / --since / --from / --to it was issued with, and expires after 24h"
)


def _translate(status: int, err: dict, request_id: str | None) -> BoostError:
    code = str(err.get("code") or f"HTTP_{status}")
    message = str(err.get("message") or "").strip()
    field, reason = _reason(err)
    where = f" [{field}/{reason}]" if field or reason else ""
    rid = f" (request_id {request_id})" if request_id else ""
    text = f"{code}{where}: {message or 'request failed'}{rid}"

    if code == "INVALID_API_KEY" or (status == 401 and code.startswith(("HTTP_", "GATEWAY"))):
        return BoostError(
            text,
            kind="auth",
            help_lines=[
                "The key is missing, wrong, expired, or its company has no active paid plan",
                *AUTH_HELP[:2],
            ],
        )
    if code == "SHOP_NOT_AUTHORIZED":
        if reason == "COMPANY_NOT_BOUND":
            hint = "The company this key belongs to has no Kaloboost account — Kaloboost data is unavailable for it"
        elif reason == "USER_NOT_IN_COMPANY":
            hint = "The KaloData user behind this key is not a member of the Kaloboost company; ask an admin to add them"
        else:
            hint = "Run `boost shops` for the shop ids this key can access (only ACTIVE, BOUND shops count)"
        return BoostError(text, kind="access", help_lines=[hint])
    if code == "RESOURCE_NOT_FOUND":
        return BoostError(
            text, kind="parameter",
            help_lines=["Ids are scoped to one shop — check the id belongs to --shop (`boost shops` lists shops)"],
        )
    if code == "CURSOR_EXPIRED" or reason == "CURSOR_INVALID":
        return BoostError(text, kind="parameter", help_lines=[_CURSOR_HELP])
    if code == "INVALID_ARGUMENT":
        return BoostError(
            text, kind="parameter",
            help_lines=[f"Fix the value behind `{field}` and retry (see `--help` of this command)"],
        )
    if code == "CHANNEL_NOT_AVAILABLE":
        if reason == "SHOP_NOT_API_AUTHORIZED":
            hint = "Ask the merchant to (re)authorize TikTok Shop Open API for this shop in Kaloboost; don't retry"
        else:
            hint = "This shop's market does not support this feature; authorizing won't help, don't retry"
        return BoostError(text, kind="access", help_lines=[hint])
    if code == "CAPABILITY_UNAVAILABLE":
        return BoostError(
            text, kind="access",
            help_lines=[
                "Not open for this key yet (PLANNED/UNAVAILABLE/NOT_IMPLEMENTED) — retrying won't help",
                "Run `boost capabilities` for what is open, `boost shops` for per-shop capabilities",
            ],
        )
    if code == "RATE_LIMITED":
        return BoostError(
            text, kind="network",
            help_lines=["Rate limited — wait a few seconds; page through one shop at a time, not in parallel"],
        )
    if code == "UPSTREAM_UNAVAILABLE" or status >= 500:
        return BoostError(text, kind="network", help_lines=["Kaloboost is temporarily unavailable; retry shortly"])
    return BoostError(text)


def request(
    cfg: Config,
    method: str,
    path: str,
    *,
    params: dict | None = None,
    body: dict | None = None,
    timeout: float = 30.0,
) -> dict:
    """Call base_url+path; return the success envelope {data, page?, request_id?}."""
    _require_auth(cfg)
    url = cfg.base_url.rstrip("/") + path
    if params:
        query = {k: v for k, v in params.items() if v not in (None, "")}
        if query:
            url += "?" + urllib.parse.urlencode(query)
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = _headers(cfg, payload is not None)

    last = "unknown error"
    for attempt in range(_RETRIES):
        try:
            status, raw, resp_headers = _do_request(url, payload, headers, timeout, method)
            parsed = _parse(raw)
            if parsed is not None and parsed.get("success") is False:
                err, rid = _gateway_error(parsed), None
            elif 200 <= status < 300:
                if parsed is None:
                    raise _Retryable("malformed JSON from upstream")
                return _unwrap(parsed)
            else:
                parsed = parsed or {}
                err = parsed.get("error")
                if not isinstance(err, dict):
                    # the gateway itself answers flat: {"code", "message", "request_id"}
                    err = parsed if "code" in parsed else {"message": str(err or "")}
                rid = parsed.get("request_id")
            code = err.get("code")
            if status == 429:
                wait = _retry_after(resp_headers)
                if wait <= _MAX_RETRY_AFTER:
                    raise _Retryable(f"HTTP 429 {code or ''}".strip(), wait=wait)
            elif status >= 500 and code != "CAPABILITY_UNAVAILABLE":
                raise _Retryable(f"HTTP {status} {code or ''}".strip())
            raise _translate(status, err, rid)
        except _Retryable as e:
            last = str(e)
            if attempt < _RETRIES - 1:
                time.sleep(e.wait if e.wait else 0.3 * (attempt + 1) + random.uniform(0, 0.2))
    raise BoostError(
        f"Kaloboost unreachable after {_RETRIES} attempts ({last})",
        kind="network",
        help_lines=["Retry shortly; check network access to " + urllib.parse.urlsplit(cfg.base_url).netloc],
    )
