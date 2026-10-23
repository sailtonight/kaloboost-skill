import base64
import datetime
import json

from conftest import err, page

from kaloboost.cli import main
from kaloboost.commands import common
from kaloboost.commands.order import merge_orders


def run(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr().out


# --- setup & usage -------------------------------------------------------------

def test_home_without_key(capsys, monkeypatch, tmp_path):
    monkeypatch.delenv("KALODATA_API_KEY", raising=False)
    monkeypatch.setenv("KALODATA_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("KALOBOOST_NO_UPDATE_CHECK", "1")
    code, out = run(capsys)
    assert code == 0
    assert "commands[" in out
    assert "auth: not configured" in out
    assert "open-center/account" in out


def test_key_is_read_from_shared_kalodata_config(capsys, monkeypatch, tmp_path, mock_server):
    monkeypatch.delenv("KALODATA_API_KEY", raising=False)
    monkeypatch.setenv("KALODATA_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("KALOBOOST_NO_UPDATE_CHECK", "1")
    monkeypatch.setenv("KALOBOOST_BASE_URL", f"http://127.0.0.1:{mock_server.server_address[1]}")
    (tmp_path / "config.toml").write_text('api_key = "from-kalo"\nregion = "GB"\n')
    code, _ = run(capsys, "capabilities")
    assert code == 0
    assert mock_server.requests[0][3]["secret-key"] == "from-kalo"


def test_config_set_keeps_kalo_keys(capsys, env, tmp_path):
    path = tmp_path / "cfg" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('api_key = "k"\nregion = "GB"\n')
    code, _ = run(capsys, "config", "set", "--shop", "shop_1", "--env", "test")
    assert code == 0
    text = path.read_text()
    assert 'region = "GB"' in text and 'api_key = "k"' in text
    assert 'boost_shop = "shop_1"' in text
    assert "testopen.kaloboost.com" in text


def test_unknown_flag_exits_2(capsys, env):
    code, out = run(capsys, "sample", "list", "--shop", "s", "--stat", "x")
    assert code == 2
    assert out.startswith("error: unknown flag --stat")
    assert "--since" in out


def test_shop_required(capsys, env):
    code, out = run(capsys, "sample", "list")
    assert code == 2
    assert "--shop is required" in out
    assert "boost shops" in out
    assert env.requests == []


def test_default_shop_from_config(capsys, env, monkeypatch):
    monkeypatch.setenv("KALOBOOST_SHOP", "shop_cfg")
    run(capsys, "sample")  # bare noun runs `sample list`
    assert env.requests[0][2]["shop_id"] == "shop_cfg"


# --- time windows ----------------------------------------------------------------

def test_parse_when_forms():
    now = datetime.datetime(2026, 10, 8, 12, 30, 15, 999, tzinfo=datetime.timezone.utc)
    assert common.parse_when("7d", now=now) == "2026-10-01T12:30:15Z"
    assert common.parse_when("24h", now=now) == "2026-10-07T12:30:15Z"
    assert common.parse_when("2026-09-01") == "2026-09-01T00:00:00Z"
    assert common.parse_when("2026-09-01T08:00:00+08:00") == "2026-09-01T00:00:00Z"


def test_order_window_over_90_days_is_rejected(capsys, env):
    code, out = run(capsys, "order", "list", "--shop", "s", "--from", "2026-01-01", "--to", "2026-06-01")
    assert code == 2
    assert "longer than 90 days" in out
    assert env.requests == []


# --- happy paths -----------------------------------------------------------------

def test_shops_table_and_headers(capsys, env):
    env.responses["/shops"] = page(
        [{"shop_id": "806", "shop_name": "Demo, Shop", "shop_region": "US", "time_zone": None,
          "capabilities": ["OUTREACH", "SAMPLE"]}]
    )
    code, out = run(capsys, "shops")
    assert code == 0
    assert "shops[1]{shop_id,shop_name,region,time_zone,capabilities}:" in out
    assert '"806","Demo, Shop",US,null,OUTREACH|SAMPLE' in out
    method, path, query, headers, _ = env.requests[0]
    assert (method, path) == ("GET", "/shops")
    assert headers["secret-key"] == "test-key"
    assert headers["source-type"] == "SKILL"
    assert headers["user-agent"].startswith("boost/")  # Cloudflare blocks urllib's default UA
    assert query["limit"] == "50"


def test_more_hint_resends_shop_and_since(capsys, env):
    env.responses["/outreach-tasks"] = page([{"outreach_task_id": "t1", "status": "RUNNING"}], cursor="CUR1")
    code, out = run(capsys, "outreach", "list", "--shop", "s1", "--since", "2026-09-01")
    assert code == 0
    assert "More: `boost outreach list --shop s1 --since 2026-09-01T00:00:00Z --cursor CUR1`" in out
    assert env.requests[0][2]["updated_from"] == "2026-09-01T00:00:00Z"


def test_all_follows_cursor_resending_filters(capsys, env):
    env.responses["/outreach-tasks"] = [
        page([{"outreach_task_id": "t1"}], cursor="C1"),
        page([{"outreach_task_id": "t2"}], cursor=None),
    ]
    code, out = run(capsys, "outreach", "list", "--shop", "s1", "--since", "2026-09-01", "--all")
    assert code == 0
    assert "outreach_tasks[2]" in out
    second = env.requests[1][2]
    assert second["cursor"] == "C1"
    assert second["shop_id"] == "s1" and second["updated_from"] == "2026-09-01T00:00:00Z"
    assert "More:" not in out


def test_collab_empty_page_with_cursor_keeps_paging_and_dedupes(capsys, env):
    env.responses["/collaborations"] = [
        page([{"outreach_cooperate_id": "1", "cooperate_status": "NOT_COOPERATED", "updated_at": "2026-09-01T00:00:00Z"}], cursor="A"),
        page([], cursor="B"),
        page([{"outreach_cooperate_id": "1", "cooperate_status": "COOPERATED", "updated_at": "2026-09-02T00:00:00Z"}], cursor=None),
    ]
    code, out = run(capsys, "collab", "list", "--shop", "s", "--all")
    assert code == 0
    assert len(env.requests) == 3
    assert "collaborations[1]" in out
    assert "COOPERATED" in out and "NOT_COOPERATED" not in out
    assert "1 duplicate rows merged" in out


def test_samples_stop_on_empty_page(capsys, env):
    env.responses["/samples"] = [
        page([{"sample_request_id": "s1", "curr_status": "SHIPPED", "fulfillment": {"video_count": 2}}], cursor="X"),
        page([], cursor="Y"),
    ]
    code, out = run(capsys, "sample", "list", "--shop", "s", "--all")
    assert code == 0
    assert len(env.requests) == 2
    assert "samples[1]" in out
    assert "SHIPPED 1" in out


def test_sample_get_reports_merged_id(capsys, env):
    env.responses["/samples/old_id"] = {"data": {"sample_request_id": "new_id", "curr_status": "COMPLETED"}}
    code, out = run(capsys, "sample", "get", "old_id", "--shop", "s")
    assert code == 0
    assert "old_id was merged into new_id" in out


def test_orders_merge_items_across_pages():
    rows = [
        {"channel_order_id": "o1", "items": [{"channel_sku_id": "a"}]},
        {"channel_order_id": "o1", "items": [{"channel_sku_id": "b"}]},
        {"channel_order_id": "o2", "items": [{"channel_sku_id": "c"}]},
    ]
    merged = merge_orders(rows)
    assert [o["channel_order_id"] for o in merged] == ["o1", "o2"]
    assert [i["channel_sku_id"] for i in merged[0]["items"]] == ["a", "b"]
    assert len(rows[0]["items"]) == 1  # input untouched


def test_order_list_totals(capsys, env):
    item = {
        "channel_product_id": "p", "quantity": 2,
        "price": {"amount": "38", "currency": "USD"},
        "creator": {"username": "lind"},
        "content": {"type": "VIDEO", "channel_content_id": "755"},
        "commission": {"rate": "0.08", "estimated": {"paid": {"amount": "3.04", "currency": "USD"}}},
        "settlement_status": "TO_SETTLE", "fully_returned": False,
    }
    env.responses["/affiliate-orders"] = page([{"channel_order_id": "o1", "created_at": "2026-09-20T08:15:30Z", "items": [item]}])
    code, out = run(capsys, "order", "list", "--shop", "s", "--from", "2026-09-01", "--to", "2026-09-29")
    assert code == 0
    assert "1 orders, 1 SKU lines · GMV 76 USD · est. commission 3.04 USD" in out
    q = env.requests[0][2]
    assert q["created_from"] == "2026-09-01T00:00:00Z" and q["created_to"] == "2026-09-29T00:00:00Z"


def test_creator_resolve_builds_items(capsys, env):
    env.responses["/creator-identities/resolve"] = {"data": {"results": [
        {"external_request_id": "@demo", "status": "MATCHED", "match_basis": "EXACT_HANDLE_FALLBACK",
         "creator": {"creator_oecuid": "cr_1", "handle": "demo", "gmv_range": "$1K-$10K"}},
        {"external_request_id": "7491234567890123456", "status": "NOT_FOUND", "match_basis": "NONE"},
    ]}}
    code, out = run(capsys, "creator", "resolve", "@demo", "7491234567890123456", "--region", "gb")
    assert code == 0
    items = env.requests[0][4]["items"]
    assert items[0] == {"external_request_id": "@demo", "shop_region": "GB", "handle": "@demo"}
    assert items[1]["creator_user_id"] == "7491234567890123456"
    assert "cr_1" in out
    assert "NOT_FOUND only searched region GB" in out


def test_creator_get_rejects_handles(capsys, env):
    code, out = run(capsys, "creator", "get", "@demo")
    assert code == 2
    assert "creator resolve" in out


def test_events_poll_hint_and_has_more(capsys, env):
    env.responses["/events"] = [
        page([{"event_id": "e1", "type": "sample.updated", "data": {"curr_status": "SHIPPED"}}], cursor="E1", has_more=True),
        page([], cursor="E2", has_more=False),
    ]
    code, out = run(capsys, "event", "list", "--shop", "s", "--types", "sample.updated", "--all")
    assert code == 0
    assert len(env.requests) == 2
    assert "SHIPPED" in out
    assert "boost event list --cursor E2" in out
    assert env.requests[0][2]["types"] == "sample.updated"


def test_event_cursor_alone_is_enough(capsys, env):
    run(capsys, "event", "list", "--cursor", "E9")
    q = env.requests[0][2]
    assert q["cursor"] == "E9" and "shop_id" not in q


def test_json_output(capsys, env):
    env.responses["/capabilities"] = {"data": {"capabilities": {"sample": "PILOT"}}}
    code, out = run(capsys, "capabilities", "--json")
    assert code == 0
    assert json.loads(out) == {"capabilities": {"sample": "PILOT"}}


# --- errors ----------------------------------------------------------------------

def test_invalid_key(capsys, env):
    env.responses["/shops"] = err(401, "INVALID_API_KEY")
    code, out = run(capsys, "shops")
    assert code == 1
    assert out.startswith("error: INVALID_API_KEY")
    assert "request_id req_test" in out
    assert "boost config set --key" in out
    assert len(env.requests) == 1  # auth failures are not retried


def test_gateway_flat_error(capsys, env):
    # shape observed from open.kaloboost.com when secret-key is missing/invalid
    env.responses["/capabilities"] = (401, {"code": "INVALID_API_KEY", "message": "invalid secret-key", "request_id": "9347d259"})
    code, out = run(capsys, "capabilities")
    assert code == 1
    assert out.startswith("error: INVALID_API_KEY: invalid secret-key (request_id 9347d259)")
    assert "boost config set --key" in out


def test_shop_not_bound_hint(capsys, env):
    env.responses["/samples"] = err(403, "SHOP_NOT_AUTHORIZED", "shop_id", "SHOP_NOT_CURRENTLY_BOUND")
    code, out = run(capsys, "sample", "list", "--shop", "nope")
    assert code == 1
    assert "[shop_id/SHOP_NOT_CURRENTLY_BOUND]" in out
    assert "boost shops" in out


def test_capability_unavailable_not_retried(capsys, env):
    env.responses["/events"] = err(503, "CAPABILITY_UNAVAILABLE", "webhook", "PLANNED")
    code, out = run(capsys, "event", "list", "--shop", "s")
    assert code == 1
    assert len(env.requests) == 1
    assert "boost capabilities" in out


def test_upstream_503_is_retried(capsys, env):
    env.responses["/shops"] = [err(503, "UPSTREAM_UNAVAILABLE"), page([{"shop_id": "1"}])]
    code, out = run(capsys, "shops")
    assert code == 0
    assert len(env.requests) == 2


def test_rate_limit_waits_then_retries(capsys, env):
    limited = (429, {"error": {"code": "RATE_LIMITED", "details": []}}, {"Retry-After": "1"})
    env.responses["/shops"] = [limited, page([{"shop_id": "1"}])]
    code, _ = run(capsys, "shops")
    assert code == 0
    assert len(env.requests) == 2


def test_cursor_invalid_hint(capsys, env):
    env.responses["/samples"] = err(400, "INVALID_ARGUMENT", "cursor", "CURSOR_INVALID")
    code, out = run(capsys, "sample", "list", "--shop", "s", "--cursor", "bad")
    assert code == 1
    assert "Drop --cursor" in out


def test_affiliate_not_authorized(capsys, env):
    env.responses["/affiliate-orders"] = err(422, "CHANNEL_NOT_AVAILABLE", "shop_id", "SHOP_NOT_API_AUTHORIZED")
    code, out = run(capsys, "order", "list", "--shop", "s")
    assert code == 1
    assert "authorize TikTok Shop Open API" in out


def test_gateway_envelope_success_and_failure(capsys, env):
    env.responses["/capabilities"] = {"success": True, "data": {"data": {"capabilities": {"outreach": "PILOT"}}, "request_id": "r"}}
    code, out = run(capsys, "capabilities")
    assert code == 0 and "outreach,PILOT,true" in out
    env.responses["/shops"] = (401, {"success": False, "code": "401", "message": "invalid secret-key"})
    code, out = run(capsys, "shops")
    assert code == 1
    assert "invalid secret-key" in out


def test_account_not_eligible_follows_first_failing_item(capsys, env):
    details = [
        {"field": "kaloboost_account", "reason": "OK", "requirement": "..."},
        {"field": "enterprise_subscription", "reason": "REQUIRED", "action": "Upgrade to Enterprise.",
         "url": "https://boost.kalowave.com", "requirement": "..."},
        {"field": "openapi_access", "reason": "NOT_CHECKED", "requirement": "..."},
    ]
    env.responses["/shops"] = err(403, "ACCOUNT_NOT_ELIGIBLE", details=details)
    code, out = run(capsys, "shops")
    assert code == 1
    assert out.startswith("error: ACCOUNT_NOT_ELIGIBLE: boom")
    assert "Blocked at enterprise_subscription: REQUIRED" in out
    assert "Upgrade to Enterprise." in out and "https://boost.kalowave.com" in out


# --- writes ----------------------------------------------------------------------

DM = ("outreach", "create", "111", "222", "--shop", "s", "--operator", "a@b.com", "--template", "T1")


def test_outreach_create_without_yes_sends_nothing(capsys, env):
    code, out = run(capsys, *DM)
    assert code == 0
    assert env.requests == []
    assert out.startswith("dry_run:")
    assert "recipients[2]{creator_oecuid}" in out
    ext = next(ln.split(": ")[1] for ln in out.splitlines() if "external_task_id" in ln)
    assert f"--external-id {ext} --yes" in out


def test_outreach_create_sends_with_external_id_as_key(capsys, env):
    env.responses["/outreach-tasks"] = (202, {"data": {"outreach_task_id": "t9", "status": "QUEUED", "total_count": 2}})
    code, out = run(capsys, *DM, "--external-id", "ext-1", "--yes")
    assert code == 0
    method, path, _, headers, body = env.requests[0]
    assert (method, path) == ("POST", "/outreach-tasks")
    assert headers["idempotency-key"] == "ext-1"
    assert headers["content-type"].startswith("application/json")
    assert body == {
        "external_task_id": "ext-1", "shop_id": "s", "operator_account": "a@b.com",
        "outreach_method": "TIKTOK_DM", "template_id": "T1",
        "recipients": [{"creator_oecuid": "111"}, {"creator_oecuid": "222"}],
    }
    assert "boost outreach recipients t9 --shop s" in out


def test_outreach_create_invitation_body(capsys, env, tmp_path):
    env.responses["/outreach-tasks"] = (202, {"data": {"outreach_task_id": "t1", "total_count": 1}})
    f = tmp_path / "c.txt"
    f.write_text("# creators\n111\n\n222\n")
    code, out = run(
        capsys, "outreach", "create", "--file", str(f), "--shop", "s", "--operator", "a@b.com",
        "--method", "TIKTOK_TARGET_COLLABORATION", "--template", "C1", "--product-template", "P1",
        "--expire", "2026-12-31T00:00:00Z", "--products", "p1,p2", "--at", "2026-11-20", "--yes",
    )
    assert code == 0
    body = env.requests[0][4]
    assert body["invitation"] == {"product_template_id": "P1", "expire_at": "2026-12-31T00:00:00Z"}
    assert body["schedule"] == {"not_before": "2026-11-20T00:00:00Z"}
    assert [r["creator_oecuid"] for r in body["recipients"]] == ["111", "222"]
    assert all(r["channel_product_ids"] == ["p1", "p2"] for r in body["recipients"])
    assert "1 creator(s) dropped: already invited" in out


def test_outreach_create_validates_locally(capsys, env):
    code, out = run(capsys, *DM, "--expire", "7d")
    assert code == 2 and "only apply to --method TIKTOK_TARGET_COLLABORATION" in out
    code, out = run(capsys, "outreach", "create", "1", "--shop", "s", "--operator", "a@b.com",
                    "--method", "TIKTOK_TARGET_COLLABORATION", "--template", "C1")
    assert code == 2 and "needs --product-template" in out
    code, out = run(capsys, "outreach", "create", "1", "--shop", "s")
    assert code == 2 and "inline content, or --template" in out
    code, out = run(capsys, "outreach", "create", "1", "--shop", "s", "--template", "T", "--text", "hi")
    assert code == 2 and "exclusive" in out
    code, out = run(capsys, "outreach", "create", *[str(i) for i in range(10001)], "--shop", "s", "--template", "T")
    assert code == 2 and "at most 10000 creators" in out
    assert env.requests == []


def test_outreach_create_operator_defaults_to_own_account(capsys, env):
    env.responses["/outreach-tasks"] = (202, {"data": {"outreach_task_id": "t1", "total_count": 1}})
    code, out = run(capsys, "outreach", "create", "111", "--shop", "s", "--template", "T1", "--yes")
    assert code == 0
    assert "operator_account" not in env.requests[0][4]
    assert "--operator" not in out


def test_outreach_create_inline_dm(capsys, env):
    env.responses["/outreach-tasks"] = (202, {"data": {"outreach_task_id": "t1", "total_count": 1}})
    code, _ = run(
        capsys, "outreach", "create", "111", "--shop", "s", "--text", "Hi ${handle}!", "--text", "More",
        "--image", "img_1", "--card", "p1", "--external-id", "e1", "--yes",
    )
    assert code == 0
    body = env.requests[0][4]
    assert "template_id" not in body and "invitation" not in body
    assert body["content"] == {"dm": {"segments": [
        {"type": "TEXT", "text": "Hi ${handle}!"}, {"type": "TEXT", "text": "More"},
        {"type": "IMAGE", "image_id": "img_1"}, {"type": "PRODUCT", "product_id": "p1"},
    ]}}


def test_outreach_create_inline_invitation(capsys, env):
    env.responses["/outreach-tasks"] = (202, {"data": {"outreach_task_id": "t1", "total_count": 1}})
    code, out = run(
        capsys, "outreach", "create", "111", "--shop", "s", "--method", "TIKTOK_TARGET_COLLABORATION",
        "--invite-name", "Zupet bottle", "--invite-message", "Hi ${handle}! Free sample?",
        "--contact", "whatsapp:812345678:th", "--contact", "EMAIL:hi@shop.co", "--sample-review", "AUTO",
        "--sync-dm", "Hi ${handle}, sent!", "--sync-dedup", "DAYS_30",
        "--products", "p1,p2:0.2", "--commission", "0.15", "--at", "2026-11-20", "--yes",
    )
    assert code == 0, out
    body = env.requests[0][4]
    assert body["invitation"] == {"expire_at": "2026-11-27T00:00:00Z"}
    assert body["content"] == {
        "invitation": {
            "invite_name": "Zupet bottle", "invite_message": "Hi ${handle}! Free sample?",
            "sample_review_type": "AUTO",
            "contacts": [{"type": "WHATSAPP", "value": "812345678", "country_code": "TH"},
                         {"type": "EMAIL", "value": "hi@shop.co"}],
            "sync_dm": {"dedup_type": "DAYS_30", "segments": [
                {"type": "TEXT", "text": "Hi ${handle}, sent!"}, {"type": "INVITE_CARD"}]},
        },
        "products": [{"product_id": "p1", "commission_rate": "0.15"}, {"product_id": "p2", "commission_rate": "0.2"}],
    }
    assert "channel_product_ids" not in body["recipients"][0]


def test_outreach_create_content_json(capsys, env):
    env.responses["/outreach-tasks"] = (202, {"data": {"outreach_task_id": "t1"}})
    content = {"dm": {"segments": [{"type": "TEXT", "text": "x"}]}}
    code, _ = run(capsys, "outreach", "create", "1", "--shop", "s", "--content", json.dumps(content), "--yes")
    assert code == 0 and env.requests[0][4]["content"] == content
    code, out = run(capsys, "outreach", "create", "1", "--shop", "s", "--content", "{}", "--text", "x")
    assert code == 2 and "replaces the content flags" in out


def test_outreach_inline_content_is_checked_locally(capsys, env):
    base = ("outreach", "create", "1", "--shop", "s")
    inv = (*base, "--method", "TIKTOK_TARGET_COLLABORATION", "--invite-name", "N", "--invite-message", "M",
           "--products", "p1")
    for argv, expect in [
        ((*base, "--text", "Hi {creator}!"), "unsupported placeholder {creator}"),
        ((*base, "--text", "Hi @${handle}"), "drop the @"),
        ((*base, "--text", "Hi {{name}}"), "unsupported placeholder {{name}}"),
        ((*base, "--image", "img"), "at least one --text"),
        ((*base, "--text", "x", "--invite-name", "N"), "only apply to --method TIKTOK_TARGET_COLLABORATION"),
        ((*inv, "--contact", "WHATSAPP:1"), "no commission for product p1"),
        ((*inv, "--contact", "WHATSAPP:1", "--commission", "15%"), "not a ratio"),
        ((*inv, "--contact", "WHATSAPP:1", "--commission", "15"), "0.01-0.80"),
        ((*inv, "--commission", "0.1"), "needs --contact"),
        ((*inv, "--commission", "0.1", "--contact", "WHATSAPP:REPLACE_WITH_MERCHANT_WHATSAPP_NUMBER"), "placeholder"),
        ((*inv, "--commission", "0.1", "--contact", "SMS:1"), "invalid --contact"),
        ((*inv, "--commission", "0.1", "--contact", "WHATSAPP:1", "--text", "x"), "build a DM"),
        ((*base, "--method", "TIKTOK_TARGET_COLLABORATION", "--invite-name", "Hi ${handle}",
          "--invite-message", "M", "--contact", "WHATSAPP:1", "--products", "p1:0.1"), "invite name can't hold"),
    ]:
        code, out = run(capsys, *argv)
        assert code == 2 and expect in out, (argv, out)
    assert env.requests == []


def test_outreach_inline_rejection_hints(capsys, env):
    env.responses["/outreach-tasks"] = err(422, "TEMPLATE_NOT_APPROVED", "content.invitation.contacts[0].type", "CONTACT_INVALID")
    code, out = run(capsys, "outreach", "create", "1", "--shop", "s", "--text", "x", "--yes")
    assert code == 1 and "never make one up" in out and len(env.requests) == 1
    env.responses["/outreach-tasks"] = err(503, "CAPABILITY_UNAVAILABLE", "content", "NOT_IMPLEMENTED")
    code, out = run(capsys, "outreach", "create", "1", "--shop", "s", "--text", "x", "--yes")
    assert code == 1 and "use --template here" in out


def test_captcha_503_is_not_retried(capsys, env):
    env.responses["/outreach-tasks"] = (503, {"error": {"code": "UPSTREAM_UNAVAILABLE", "message": "m"}}, {"Retry-After": "300"})
    env.requests.clear()
    code, out = run(capsys, "outreach", "create", "1", "--shop", "s", "--text", "x", "--external-id", "e", "--yes")
    assert code == 1 and len(env.requests) == 1
    assert "wait at least 300s" in out and "--external-id e" in out


def test_outreach_products(capsys, env, monkeypatch):
    slept = []
    monkeypatch.setattr("kaloboost.commands.common.time.sleep", slept.append)
    env.responses["/outreach-products"] = [
        page([{"product_id": "p1", "title": "Bottle", "price": {"min_format": "$1", "max_format": "$2"},
               "selectable": True}], cursor="C"),
        page([{"product_id": "p1", "selectable": True},
              {"product_id": "p2", "selectable": False, "unselectable_reason": "OUT_OF_STOCK"}]),
    ]
    code, out = run(capsys, "outreach", "products", "--shop", "s", "--method", "TIKTOK_TARGET_COLLABORATION",
                    "--keyword", "bot", "--all")
    assert code == 0
    assert "products[2]" in out and "OUT_OF_STOCK" in out and "--products <product_id>" in out
    q = env.requests[0][2]
    assert q == {"shop_id": "s", "outreach_method": "TIKTOK_TARGET_COLLABORATION", "keyword": "bot", "limit": "20"}
    assert slept == [1.0]


def test_outreach_upload_image(capsys, env, tmp_path):
    img = tmp_path / "bottle.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 10)
    env.responses["/outreach-images"] = {"data": {"image_id": "img_abc", "width": 1, "height": 1}}
    code, out = run(capsys, "outreach", "upload-image", str(img), "--shop", "s")
    assert code == 0 and "--image img_abc" in out
    method, path, _, headers, body = env.requests[0]
    assert (method, path) == ("POST", "/outreach-images") and "idempotency-key" not in headers
    assert body["file_name"] == "bottle.png"
    assert base64.b64decode(body["file_base64"]) == img.read_bytes()
    bad = tmp_path / "notes.txt"
    bad.write_text("secret")
    code, out = run(capsys, "outreach", "upload-image", str(bad), "--shop", "s")
    assert code == 2 and "not a JPG or PNG" in out and len(env.requests) == 1


def test_outreach_create_template(capsys, env):
    argv = ("outreach", "create-template", "--shop", "s", "--name", "Bottle", "--products", "p1", "--commission", "0.15")
    code, out = run(capsys, *argv)
    assert code == 0 and env.requests == [] and out.startswith("dry_run:")
    assert "idempotency_key" not in out
    env.responses["/outreach-templates"] = {"data": {"template_id": "tpl1", "template_type": "INVITE_PRODUCT"}}
    code, out = run(capsys, *argv, "--yes")
    assert code == 0 and "--product-template tpl1" in out
    _, path, _, headers, body = env.requests[0]
    assert path == "/outreach-templates" and "idempotency-key" not in headers
    assert body == {"shop_id": "s", "template_name": "Bottle",
                    "products": [{"product_id": "p1", "commission_rate": "0.15"}]}
    code, out = run(capsys, "outreach", "create-template", "--shop", "s", "--name", "X", "--text", "a",
                    "--products", "p1")
    assert code == 2 and "exactly one of" in out


def test_outreach_create_template_is_not_retried(capsys, env):
    env.responses["/outreach-templates"] = err(503, "UPSTREAM_UNAVAILABLE")
    code, out = run(capsys, "outreach", "create-template", "--shop", "s", "--name", "DM1", "--text", "hi", "--yes")
    assert code == 1 and len(env.requests) == 1
    assert "look for 'DM1'" in out


def test_outreach_create_503_keeps_key_and_hints_retry(capsys, env):
    env.responses["/outreach-tasks"] = err(503, "UPSTREAM_UNAVAILABLE")
    code, out = run(capsys, *DM, "--external-id", "ext-7", "--yes")
    assert code == 1
    assert len(env.requests) == 3
    assert {r[3]["idempotency-key"] for r in env.requests} == {"ext-7"}
    assert "--external-id ext-7" in out


def test_outreach_create_conflict_hints(capsys, env):
    env.responses["/outreach-tasks"] = err(409, "IDEMPOTENCY_CONFLICT", "external_task_id", "EXTERNAL_ID_IN_USE")
    code, out = run(capsys, *DM, "--yes")
    assert code == 1
    assert "already created a task" in out


def test_outreach_create_waits_for_in_progress(capsys, env, monkeypatch):
    slept = []
    monkeypatch.setattr("kaloboost.commands.outreach.time.sleep", slept.append)
    env.responses["/outreach-tasks"] = [
        err(409, "IDEMPOTENCY_CONFLICT", "Idempotency-Key", "IN_PROGRESS"),
        (202, {"data": {"outreach_task_id": "t5", "total_count": 1}}),
    ]
    code, out = run(capsys, *DM, "--external-id", "ext-9", "--yes")
    assert code == 0 and "t5" in out
    assert [r[3]["idempotency-key"] for r in env.requests] == ["ext-9", "ext-9"]
    assert slept == [20.0]


def test_outreach_recipients_explain_creator_failures(capsys, env):
    env.responses["/outreach-tasks/t1/recipients"] = page([
        {"creator_oecuid": "1", "send_status": "SEND_FAILED", "error_code": "TARGET_INVITATION_UNAVAILABLE_CREATOR"},
    ])
    code, out = run(capsys, "outreach", "recipients", "t1", "--shop", "s")
    assert code == 0 and "ask the user for other creators" in out


def test_outreach_cancel(capsys, env):
    env.responses["/outreach-tasks/t1:cancel"] = (202, {"data": {"outreach_task_id": "t1", "status": "CANCELED"}})
    code, out = run(capsys, "outreach", "cancel", "t1", "--shop", "s", "--operator", "+86 138",
                    "--idempotency-key", "k1", "--yes")
    assert code == 0
    method, path, query, headers, body = env.requests[0]
    assert (method, path, body) == ("POST", "/outreach-tasks/t1:cancel", None)
    assert query == {"shop_id": "s", "operator_account": "+86 138"}
    assert headers["idempotency-key"] == "k1"
    assert "CANCELED" in out


def test_webhook_create_shows_secret_once(capsys, env, monkeypatch):
    monkeypatch.setenv("KALOBOOST_SHOP", "s_cfg")
    env.responses["/webhook-endpoints"] = {"data": {"endpoint_id": "whe_1", "status": "ACTIVE", "secret": "whsec_x"}}
    code, out = run(capsys, "webhook", "create", "--url", "https://h.example.com/k", "--yes")
    assert code == 0
    body = env.requests[0][4]
    assert body["shop_ids"] == ["s_cfg"]
    assert body["event_types"] == list(common.EVENT_TYPES)
    assert "whsec_x" in out and "shown only this once" in out


def test_webhook_update_is_patch(capsys, env):
    env.responses["/webhook-endpoints/whe_1"] = {"data": {"endpoint_id": "whe_1", "status": "ACTIVE"}}
    code, out = run(capsys, "webhook", "update", "whe_1", "--status", "ACTIVE", "--shop", "a", "--shop", "b,c", "--yes")
    assert code == 0
    method, path, _, _, body = env.requests[0]
    assert (method, path) == ("PATCH", "/webhook-endpoints/whe_1")
    assert body == {"shop_ids": ["a", "b", "c"], "status": "ACTIVE"}
    assert "webhook replay whe_1" in out


def test_webhook_replay_and_list(capsys, env):
    env.responses["/webhook-endpoints/whe_1:replay"] = (202, {"data": {"replay_id": "whr_1"}})
    code, out = run(capsys, "webhook", "replay", "whe_1", "--from", "2026-10-01", "--to", "2026-10-02",
                    "--types", "sample.updated", "--yes")
    assert code == 0
    assert env.requests[0][4] == {"occurred_from": "2026-10-01T00:00:00Z", "occurred_to": "2026-10-02T00:00:00Z",
                                  "event_types": ["sample.updated"]}
    env.responses["/webhook-endpoints"] = {"data": [{"endpoint_id": "whe_1", "status": "PAUSED", "paused_reason": "AUTO_4XX",
                                                     "event_types": ["sample.updated"], "shop_ids": ["s"]}]}
    code, out = run(capsys, "webhook")
    assert code == 0
    assert "whe_1,PAUSED,AUTO_4XX" in out
    assert "--status ACTIVE" in out


# --- other new reads -------------------------------------------------------------

def test_resolve_job_flow(capsys, env):
    env.responses["/identity-resolution-jobs"] = {"data": {"job_id": "irj_1", "status": "QUEUED", "total_count": 2}}
    code, out = run(capsys, "resolve-job", "create", "@a", "7491234567890123456", "--region", "GB")
    assert code == 0
    _, _, _, headers, body = env.requests[0]
    assert headers["idempotency-key"]
    assert body["items"][1] == {"external_request_id": "7491234567890123456", "shop_region": "GB",
                                "creator_user_id": "7491234567890123456"}
    assert "boost resolve-job get irj_1" in out
    env.responses["/identity-resolution-jobs/irj_1/results"] = page(
        [{"external_request_id": "@a", "status": "MATCHED", "creator": {"creator_oecuid": "c1"}}]
    )
    code, out = run(capsys, "resolve-job", "results", "irj_1")
    assert code == 0
    assert "MATCHED 1" in out and "c1" in out


def test_creator_resolve_over_100_points_to_job(capsys, env):
    code, out = run(capsys, "creator", "resolve", *[f"@c{i}" for i in range(101)])
    assert code == 2
    assert "resolve-job create" in out


def test_content_list_filters_and_more_hint(capsys, env):
    env.responses["/creator-content"] = page(
        [{"content_id": "cnt_1", "content_type": "VIDEO", "metrics": {"watch_cnt": 10, "direct_gmv_amount": "1.5",
                                                                     "currency_code": "USD"}}], cursor="C1")
    code, out = run(capsys, "content", "--shop", "s", "--creator", "cr", "--published-from", "2026-09-01")
    assert code == 0
    q = env.requests[0][2]
    assert q["creator_oecuid"] == "cr" and q["published_time_from"] == "2026-09-01T00:00:00Z"
    assert "1.5 USD" in out
    assert "boost content list --shop s --creator cr --published-from 2026-09-01T00:00:00Z --cursor C1" in out


def test_attribution_not_implemented(capsys, env):
    env.responses["/affiliate-attributions"] = err(503, "CAPABILITY_UNAVAILABLE", "affiliate_attribution", "NOT_IMPLEMENTED")
    code, out = run(capsys, "attribution", "list", "--shop", "s")
    assert code == 1
    assert len(env.requests) == 1
    assert "not live on the server yet" in out


def test_creator_changes(capsys, env):
    env.responses["/creator-changes"] = page([{"creator_oecuid": "c1", "resource_version": 3,
                                               "change_mask": ["identity.handle", "metrics.follower_count"],
                                               "creator": {"identity": {"handle": "new"}}}])
    code, out = run(capsys, "creator", "changes", "--region", "us", "--since", "2026-10-01")
    assert code == 0
    assert env.requests[0][2]["shop_region"] == "US"
    assert "identity.handle metrics.follower_count" in out


# --- chat ------------------------------------------------------------------------

def test_chat_list_caps_limit_and_repeats_filters(capsys, env):
    env.responses["/chat/conversations"] = page(
        [{"conversation_id": "c1", "username": "amy", "unread_count": 2, "creator_im_id": "im1"}], cursor="n2",
    )
    code, out = run(capsys, "chat", "--shop", "s", "--status", "UNREAD", "--limit", "50")
    assert code == 0
    assert env.requests[0][2] == {"shop_id": "s", "conversation_status": "UNREAD", "limit": "50"}
    assert "boost chat list --shop s --status UNREAD --limit 50 --cursor n2" in out
    code, out = run(capsys, "chat", "list", "--shop", "s", "--limit", "51")
    assert code == 2 and "--limit must be 1-50" in out


def test_chat_messages_render_text_and_cards(capsys, env):
    env.responses["/chat/conversations/c%2F1/messages"] = page([
        {"message_id": "m1", "sender_role": "CREATOR", "msg_type": "TEXT", "content": {"content": "Hi!"},
         "created_at": "2026-10-22T00:00:00Z"},
        {"message_id": "m2", "sender_role": "MERCHANT", "msg_type": "PRODUCT_CARD", "content": {"product_id": "9"}},
        {"message_id": "m3", "sender_role": "UNKNOWN", "msg_type": "SYSTEM", "content": None, "content_raw": "raw"},
    ])
    code, out = run(capsys, "chat", "messages", "c/1", "--shop", "s", "--limit", "30")
    assert code == 2 and "1-20" in out
    code, out = run(capsys, "chat", "messages", "c/1", "--shop", "s")
    assert code == 0
    assert env.requests[-1][1] == "/chat/conversations/c%2F1/messages"
    assert "Hi!" in out and "[product] 9" in out and "raw" in out


def test_chat_send_is_dry_run_until_yes(capsys, env):
    code, out = run(capsys, "chat", "send", "c1", "--shop", "s", "--text", "Hello")
    assert code == 0 and "dry_run" in out and env.requests == []
    code, _ = run(capsys, "chat", "send", "c1", "--shop", "s", "--text", "Hello", "--idempotency-key", "k1", "--yes")
    assert code == 0
    method, path, _, headers, body = env.requests[0]
    assert (method, path) == ("POST", "/chat/conversations/c1/messages")
    assert headers["idempotency-key"] == "k1"
    assert body == {"shop_id": "s", "msg_type": "TEXT", "content": {"content": "Hello"}}


def _sent(capsys, env, *flags):
    code, out = run(capsys, "chat", "send", "c1", "--shop", "s", *flags, "--json")
    assert code == 0, out
    return json.loads(out)["dry_run"]["body"]


def test_chat_send_picks_msg_type_from_flags(capsys, env):
    assert _sent(capsys, env, "--image", "https://x/a.png", "--width", "8", "--height", "6") == {
        "shop_id": "s", "msg_type": "IMAGE", "content": {"url": "https://x/a.png", "width": 8, "height": 6}}
    assert _sent(capsys, env, "--product", "11")["msg_type"] == "PRODUCT_CARD"
    body = _sent(capsys, env, "--text", "Look", "--product", "11,12", "--title", "Picks")
    assert body["msg_type"] == "CRM_TEXT_WITH_PRODUCTS_CARD"
    assert body["content"] == {"product_ids": "11,12", "content": "Look", "title": "Picks"}
    body = _sent(capsys, env, "--text", "See", "--image", "https://x/a.png")
    assert body["content"] == {"image_url": "https://x/a.png", "content": "See"}
    assert _sent(capsys, env, "--collab", "77")["content"] == {"target_collaboration_id": "77"}
    assert _sent(capsys, env, "--sample", "88", "--operator", "a@b.com") == {
        "shop_id": "s", "msg_type": "FREE_SAMPLE_CARD", "content": {"apply_id": "88"}, "operator_account": "a@b.com"}
    assert env.requests == []


def test_chat_send_validates_locally(capsys, env):
    cases = [
        ((), "nothing to send"),
        (("--image", "u"), "--width and --height"),
        (("--text", "x" * 2001), "at most 2000"),
        (("--text", "x" * 501, "--product", "1"), "at most 500"),
        (("--text", "x", "--product", "1,2,3,4,5,6"), "1-5 products"),
        (("--product", "1,2"), "one --product"),
        (("--product", "abc"), "must be TikTok product ids"),
        (("--collab", "1", "--text", "x"), "card of its own"),
        (("--text", "x", "--title", "t"), "--title only"),
        (("--text", "x", "--image", "u", "--product", "1"), "not both"),
    ]
    for flags, msg in cases:
        code, out = run(capsys, "chat", "send", "c1", "--shop", "s", *flags)
        assert code == 2 and msg in out, (flags, out)
    assert env.requests == []


def test_chat_send_outcome_unknown_is_not_retried(capsys, env):
    env.responses["/chat/conversations/c1/messages"] = err(
        503, "UPSTREAM_UNAVAILABLE", "submission", "OUTCOME_UNKNOWN")
    code, out = run(capsys, "chat", "send", "c1", "--shop", "s", "--text", "Hi", "--yes")
    assert code == 1
    assert len(env.requests) == 1
    assert "may already have been sent" in out
    assert "retry the identical command" not in out
    assert "retry shortly" not in out


def test_chat_send_not_submitted_exhausted_keeps_verdict(capsys, env):
    env.responses["/chat/conversations/c1/messages"] = err(
        503, "UPSTREAM_UNAVAILABLE", "submission", "NOT_SUBMITTED")
    code, out = run(capsys, "chat", "send", "c1", "--shop", "s", "--text", "Hi", "--idempotency-key", "k", "--yes")
    assert code == 1
    assert len(env.requests) == 3
    assert "Not sent to TikTok" in out
    assert "may have been sent" not in out and "unreachable" not in out


def test_chat_send_not_submitted_is_retried_with_same_key(capsys, env):
    env.responses["/chat/conversations/c1/messages"] = [
        err(503, "UPSTREAM_UNAVAILABLE", "submission", "NOT_SUBMITTED"),
        {"data": {"accepted": True, "conversation_id": "c1", "msg_type": "TEXT", "message_id": None}},
    ]
    code, out = run(capsys, "chat", "send", "c1", "--shop", "s", "--text", "Hi", "--yes")
    assert code == 0 and "accepted" in out
    keys = {r[3]["idempotency-key"] for r in env.requests}
    assert len(env.requests) == 2 and len(keys) == 1


def test_chat_open_and_read(capsys, env):
    env.responses["/chat/conversations"] = {"data": {"conversation_id": "c9", "is_new": True}}
    code, out = run(capsys, "chat", "open", "oec1", "--shop", "s")
    assert code == 0 and "boost chat messages c9" in out
    assert env.requests[0][4] == {"shop_id": "s", "creator_oecuid": "oec1"}
    assert env.requests[0][3]["idempotency-key"]
    env.responses["/chat/conversations:markRead"] = {"data": {"failed_conversation_ids": ["c2"]}}
    code, out = run(capsys, "chat", "read", "c1", "c2", "--shop", "s")
    assert code == 0 and "marked_read: 1 of 2" in out and "failed[1]: c2" in out
    assert env.requests[1][4] == {"shop_id": "s", "conversation_ids": ["c1", "c2"]}
    code, out = run(capsys, "chat", "read", "c1", "c1", "--shop", "s")
    assert code == 2


def test_chat_status(capsys, env):
    env.responses["/chat/conversations/c1/status"] = {"data": {"conversation_id": "c1", "action": "ARCHIVED"}}
    code, _ = run(capsys, "chat", "status", "c1", "--shop", "s", "--action", "ARCHIVED")
    assert code == 0
    assert env.requests[0][4] == {"shop_id": "s", "action": "ARCHIVED"}
    code, out = run(capsys, "chat", "status", "c1", "--shop", "s")
    assert code == 2 and "--action is required" in out


def test_chat_upload_image_is_multipart(capsys, env, tmp_path):
    img = tmp_path / "a.webp"
    img.write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 data")
    env.responses["/chat/images"] = {"data": {"url": "https://img/x.webp", "width": 10, "height": 20}}
    code, out = run(capsys, "chat", "upload-image", str(img), "--shop", "s", "--operator", "a@b.com")
    assert code == 0
    assert "--image 'https://img/x.webp' --width 10 --height 20" in out
    _, path, _, headers, body = env.requests[0]
    assert path == "/chat/images"
    assert headers["content-type"].startswith("multipart/form-data; boundary=")
    assert headers["idempotency-key"]
    assert b'name="shop_id"\r\n\r\ns\r\n' in body
    assert b'name="operator_account"\r\n\r\na@b.com\r\n' in body
    assert b'filename="a.webp"\r\nContent-Type: image/webp\r\n\r\nRIFF' in body
    bad = tmp_path / "a.txt"
    bad.write_text("nope")
    code, out = run(capsys, "chat", "upload-image", str(bad), "--shop", "s")
    assert code == 2 and "not a JPG, PNG, GIF or WebP" in out


def test_event_list_explains_chat_events(capsys, env):
    env.responses["/events"] = page([{
        "event_id": "e1", "type": "chat.message.created", "resource_id": "opaque",
        "data": {"conversation_id": "c1", "sender_role": "CREATOR", "msg_type": "TEXT"},
    }])
    code, out = run(capsys, "event", "list", "--shop", "s", "--types", "chat.message.created")
    assert code == 0
    assert "CREATOR TEXT in c1" in out
    assert "boost chat messages" in out
